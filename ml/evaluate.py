import os
import json
import time
import torch
import numpy as np
from torch.utils.data import DataLoader

from ml.dataset import SAROilSpillDataset
from ml.models import get_segmentation_model


def evaluate_model_on_test_set(model_name, checkpoint_path, test_samples, device, batch_size=8, threshold=0.5):
    print(f"\n========================================================")
    print(f" EVALUATING TEST SET: {model_name.upper()}")
    print(f" Checkpoint: {checkpoint_path}")
    print(f"========================================================")

    model = get_segmentation_model(model_name=model_name, in_channels=3, num_classes=1).to(device)
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    test_loader = DataLoader(SAROilSpillDataset(test_samples, is_train=False), batch_size=batch_size, shuffle=False)

    total_tp = 0
    total_fp = 0
    total_fn = 0
    total_tn = 0
    total_lookalike_negatives = 0
    false_alarms_on_lookalikes = 0

    inference_times = []

    with torch.no_grad():
        for batch in test_loader:
            images = batch["image"].to(device)
            masks = batch["mask"].to(device)

            t0 = time.time()
            logits = model(images)
            t1 = time.time()
            inference_times.append((t1 - t0) / images.size(0))

            probs = torch.sigmoid(logits)
            preds = (probs > threshold).float()

            preds_np = preds.cpu().numpy().astype(bool)
            masks_np = masks.cpu().numpy().astype(bool)

            for i in range(images.size(0)):
                p = preds_np[i, 0]
                m = masks_np[i, 0]

                tp = np.logical_and(p, m).sum()
                fp = np.logical_and(p, np.logical_not(m)).sum()
                fn = np.logical_and(np.logical_not(p), m).sum()
                tn = np.logical_and(np.logical_not(p), np.logical_not(m)).sum()

                total_tp += tp
                total_fp += fp
                total_fn += fn
                total_tn += tn

                # Check if this was a pure negative/lookalike tile
                if m.sum() == 0:
                    total_lookalike_negatives += 1
                    if p.sum() > 50:  # more than 50 false alarm pixels
                        false_alarms_on_lookalikes += 1

    # Aggregate global metrics
    epsilon = 1e-7
    iou = (total_tp + epsilon) / (total_tp + total_fp + total_fn + epsilon)
    dice = (2.0 * total_tp + epsilon) / (2.0 * total_tp + total_fp + total_fn + epsilon)
    precision = (total_tp + epsilon) / (total_tp + total_fp + epsilon)
    recall = (total_tp + epsilon) / (total_tp + total_fn + epsilon)
    accuracy = (total_tp + total_tn) / (total_tp + total_fp + total_fn + total_tn + epsilon)
    lookalike_fpr = (false_alarms_on_lookalikes / max(1, total_lookalike_negatives))

    avg_latency_ms = round(np.mean(inference_times) * 1000, 2)

    results = {
        "model_name": model_name,
        "checkpoint": checkpoint_path,
        "test_samples_count": len(test_samples),
        "metrics": {
            "mean_iou_percentage": round(float(iou) * 100, 2),
            "dice_similarity_f1": round(float(dice), 4),
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "pixel_accuracy_percentage": round(float(accuracy) * 100, 2),
            "lookalike_false_positive_rate": round(float(lookalike_fpr), 4)
        },
        "performance": {
            "avg_inference_latency_ms": avg_latency_ms,
            "device": str(device)
        }
    }

    print(f" -> Mean IoU:          {results['metrics']['mean_iou_percentage']}%")
    print(f" -> Dice / F1 Score:   {results['metrics']['dice_similarity_f1']}")
    print(f" -> Precision:         {results['metrics']['precision']}")
    print(f" -> Recall:            {results['metrics']['recall']}")
    print(f" -> Pixel Accuracy:    {results['metrics']['pixel_accuracy_percentage']}%")
    print(f" -> Lookalike FPR:     {results['metrics']['lookalike_false_positive_rate']}")
    print(f" -> Latency per Tile:  {avg_latency_ms} ms")

    return results


def evaluate_real_deepsar_test_set(
    checkpoint_path="ml/checkpoints/real_deepsar_unet_v2_best.pth",
    data_dir="data/real_deep_sar",
    out_file="ml/results/real_deepsar_v2_test_evaluation_report.json"
):
    from ml.dataset import load_real_deepsar_splits, RealDeepSARDataset
    os.makedirs("ml/results", exist_ok=True)
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for evaluation.")
    device = torch.device("cuda")

    train_pairs, val_pairs, test_pairs = load_real_deepsar_splits(data_dir=data_dir)
    print(f"Loaded {len(test_pairs)} held-out test pairs for final evaluation.")

    val_palsar = [p for p in test_pairs if 'palsar' in os.path.basename(p[0]).lower()]
    val_sentinel = [p for p in test_pairs if 'sentinel' in os.path.basename(p[0]).lower()]

    model = get_segmentation_model('unet', in_channels=3, num_classes=1).to(device)
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    state_dict = checkpoint['state_dict'] if 'state_dict' in checkpoint else checkpoint['model_state']
    model.load_state_dict(state_dict)
    model.eval()

    def eval_subset(subset_name, samples):
        loader = DataLoader(RealDeepSARDataset(samples, is_train=False), batch_size=16, shuffle=False)
        total_tp = 0
        total_fp = 0
        total_fn = 0
        total_tn = 0
        latencies = []

        with torch.no_grad():
            for batch in loader:
                images = batch["image"].to(device)
                masks = batch["mask"].to(device)

                t0 = time.time()
                logits = model(images)
                t1 = time.time()
                latencies.append((t1 - t0) / images.size(0))

                probs = torch.sigmoid(logits)
                preds = (probs > 0.5).float()

                p_np = preds.cpu().numpy().astype(bool)[:, 0]
                m_np = masks.cpu().numpy().astype(bool)[:, 0]

                for i in range(images.size(0)):
                    p = p_np[i]
                    m = m_np[i]
                    total_tp += np.logical_and(p, m).sum()
                    total_fp += np.logical_and(p, np.logical_not(m)).sum()
                    total_fn += np.logical_and(np.logical_not(p), m).sum()
                    total_tn += np.logical_and(np.logical_not(p), np.logical_not(m)).sum()

        eps = 1e-7
        iou = (total_tp + eps) / (total_tp + total_fp + total_fn + eps)
        dice = (2.0 * total_tp + eps) / (2.0 * total_tp + total_fp + total_fn + eps)
        precision = (total_tp + eps) / (total_tp + total_fp + eps)
        recall = (total_tp + eps) / (total_tp + total_fn + eps)
        accuracy = (total_tp + total_tn) / (total_tp + total_fp + total_fn + total_tn + eps)
        avg_latency = np.mean(latencies) * 1000

        print(f"\n========================================================")
        print(f" TEST SPLIT: {subset_name.upper()} ({len(samples)} pairs)")
        print(f"========================================================")
        print(f" -> Mean IoU:          {iou * 100:.2f}%")
        print(f" -> Dice / F1 Score:   {dice:.4f}")
        print(f" -> Precision:         {precision:.4f}")
        print(f" -> Recall:            {recall:.4f}")
        print(f" -> Pixel Accuracy:    {accuracy * 100:.2f}%")
        print(f" -> Latency per Tile:  {avg_latency:.2f} ms")

        return {
            "subset": subset_name,
            "sample_count": len(samples),
            "metrics": {
                "mean_iou_percentage": round(float(iou) * 100, 2),
                "dice_similarity_f1": round(float(dice), 4),
                "precision": round(float(precision), 4),
                "recall": round(float(recall), 4),
                "pixel_accuracy_percentage": round(float(accuracy) * 100, 2)
            },
            "performance": {
                "avg_inference_latency_ms": round(float(avg_latency), 2),
                "device": str(device)
            }
        }

    report = {
        "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checkpoint": checkpoint_path,
        "dataset": "Refined Deep-SAR (SOS) Zenodo 15298010",
        "results": {
            "palsar_test_set": eval_subset("PALSAR Test Set", val_palsar),
            "sentinel_test_set": eval_subset("Sentinel-1 Test Set", val_sentinel),
            "combined_test_set": eval_subset("Combined Test Set", test_pairs)
        }
    }

    with open(out_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nFull evaluation report saved to: {out_file}")
    return report


def evaluate_v3_dualpol_val_set(
    checkpoint_path="ml/checkpoints/v3_dualpol_best.pth",
    model_name="deeplabv3plus",
    in_channels=2,
    val_samples=None,
    out_file="ml/results/v3_dualpol_val_evaluation_report.json"
):
    """
    Evaluates trained V3 dual-polarization model against validation samples,
    computing overall and category-stratified metrics (Oil Spill vs No-Oil vs Lookalike).
    """
    from ml.dataset import DualPolSARSegmentationDataset
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    print(f"\n========================================================")
    print(f" EVALUATING V3 DUAL-POL MODEL ({model_name.upper()}) on {device}")
    print(f" Checkpoint: {checkpoint_path}")
    print(f"========================================================")

    model = get_segmentation_model(model_name=model_name, in_channels=in_channels, num_classes=1).to(device)
    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    state_dict = checkpoint["state_dict"] if "state_dict" in checkpoint else checkpoint["model_state"]
    model.load_state_dict(state_dict)
    model.eval()

    loader = DataLoader(DualPolSARSegmentationDataset(val_samples, is_train=False, add_diff_channel=(in_channels == 3)), batch_size=8, shuffle=False)

    total_tp = 0
    total_fp = 0
    total_fn = 0
    total_tn = 0
    total_lookalike_pixels = 0
    false_alarm_lookalike_pixels = 0
    inference_times = []

    with torch.no_grad():
        for batch in loader:
            images = batch["image"].to(device)
            masks = batch["mask"].to(device)
            categories = batch["category"]

            t0 = time.time()
            logits = model(images)
            t1 = time.time()
            inference_times.append((t1 - t0) / images.size(0))

            probs = torch.sigmoid(logits)
            preds = (probs > 0.5).float()

            preds_np = preds.cpu().numpy().astype(bool)[:, 0]
            masks_np = masks.cpu().numpy().astype(bool)[:, 0]

            for i in range(images.size(0)):
                p = preds_np[i]
                m = masks_np[i]
                cat = categories[i]

                tp = np.logical_and(p, m).sum()
                fp = np.logical_and(p, np.logical_not(m)).sum()
                fn = np.logical_and(np.logical_not(p), m).sum()
                tn = np.logical_and(np.logical_not(p), np.logical_not(m)).sum()

                total_tp += tp
                total_fp += fp
                total_fn += fn
                total_tn += tn

                if cat == "lookalike":
                    total_lookalike_pixels += p.size
                    false_alarm_lookalike_pixels += p.sum()

    eps = 1e-7
    iou = (total_tp + eps) / (total_tp + total_fp + total_fn + eps)
    dice = (2.0 * total_tp + eps) / (2.0 * total_tp + total_fp + total_fn + eps)
    precision = (total_tp + eps) / (total_tp + total_fp + eps)
    recall = (total_tp + eps) / (total_tp + total_fn + eps)
    accuracy = (total_tp + total_tn) / (total_tp + total_fp + total_fn + total_tn + eps)
    lookalike_fpr = (false_alarm_lookalike_pixels + eps) / (total_lookalike_pixels + eps)
    avg_latency = np.mean(inference_times) * 1000 if inference_times else 0.0

    report = {
        "evaluation_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checkpoint": checkpoint_path,
        "model_name": model_name,
        "validation_samples_count": len(val_samples) if val_samples else 0,
        "metrics": {
            "mean_iou_percentage": round(float(iou) * 100, 2),
            "dice_similarity_f1": round(float(dice), 4),
            "precision": round(float(precision), 4),
            "recall": round(float(recall), 4),
            "pixel_accuracy_percentage": round(float(accuracy) * 100, 2),
            "lookalike_false_positive_rate": round(float(lookalike_fpr), 6)
        },
        "performance": {
            "avg_inference_latency_ms": round(float(avg_latency), 2),
            "device": str(device)
        }
    }

    print(f"\n========================================================")
    print(f" VALIDATION EVALUATION RESULTS")
    print(f"========================================================")
    print(f" -> Mean IoU:          {report['metrics']['mean_iou_percentage']}%")
    print(f" -> Dice / F1 Score:   {report['metrics']['dice_similarity_f1']}")
    print(f" -> Precision:         {report['metrics']['precision']}")
    print(f" -> Recall:            {report['metrics']['recall']}")
    print(f" -> Pixel Accuracy:    {report['metrics']['pixel_accuracy_percentage']}%")
    print(f" -> Lookalike FPR:     {report['metrics']['lookalike_false_positive_rate']}")
    print(f" -> Latency per Patch: {report['performance']['avg_inference_latency_ms']} ms")

    with open(out_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport saved to: {out_file}")
    return report


if __name__ == "__main__":
    ckpt = "ml/checkpoints/real_deepsar_unet_v2_best.pth"
    if os.path.exists(ckpt):
        evaluate_real_deepsar_test_set(checkpoint_path=ckpt)
    elif os.path.exists("ml/checkpoints/real_deepsar_unet_best.pth"):
        evaluate_real_deepsar_test_set(checkpoint_path="ml/checkpoints/real_deepsar_unet_best.pth")
    else:
        print("No real Deep-SAR checkpoint found to evaluate.")



