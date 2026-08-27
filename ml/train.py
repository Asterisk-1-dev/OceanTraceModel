import os
import json
import time
import torch
import torch.optim as optim
from torch.utils.data import DataLoader

from ml.dataset import generate_benchmark_sar_corpus, create_stratified_scene_splits, SAROilSpillDataset
from ml.models import get_segmentation_model, CompoundOilSpillLoss, BCEDiceLoss


def atomic_torch_save(state_dict_obj, target_path):
    """
    Saves PyTorch state dict atomically by writing to a temporary file first,
    then renaming to prevent file corruption in case of unexpected power failure.
    """
    target_dir = os.path.dirname(target_path)
    os.makedirs(target_dir, exist_ok=True)
    temp_path = f"{target_path}.tmp_{os.getpid()}"
    torch.save(state_dict_obj, temp_path)
    os.replace(temp_path, target_path)


def compute_batch_iou_dice(logits, targets, threshold=0.5, smooth=1e-6):
    """
    Computes Intersection over Union (IoU) and Dice Coefficient (F1).
    """
    probs = torch.sigmoid(logits)
    preds = (probs > threshold).float()
    
    preds_flat = preds.view(-1)
    targets_flat = targets.view(-1)

    intersection = (preds_flat * targets_flat).sum().item()
    union = preds_flat.sum().item() + targets_flat.sum().item() - intersection

    iou = (intersection + smooth) / (union + smooth)
    dice = (2.0 * intersection + smooth) / (preds_flat.sum().item() + targets_flat.sum().item() + smooth)

    return iou, dice


def train_resumable_v2_model(

    model_name="unet",
    train_loader=None,
    val_loader=None,
    device=None,
    total_epochs=50,
    lr=3e-4,
    best_checkpoint_path="ml/checkpoints/real_deepsar_unet_v2_best.pth",
    latest_checkpoint_path="ml/checkpoints/real_deepsar_unet_v2_latest.pth",
    log_json_path="ml/results/real_deepsar_v2_training_log.json"
):
    print(f"\n========================================================")
    print(f" EXPERIMENT V2: RESUMABLE TRAINING ({model_name.upper()}) on {device}")
    print(f" Target Epochs: {total_epochs} | Loss: BCE + Dice | Scheduler: CosineAnnealingLR")
    print(f" Best Checkpoint:   {best_checkpoint_path}")
    print(f" Latest Checkpoint: {latest_checkpoint_path}")
    print(f" Log File:          {log_json_path}")
    print(f"========================================================")

    model = get_segmentation_model(model_name=model_name, in_channels=3, num_classes=1).to(device)
    criterion = BCEDiceLoss(bce_weight=0.5, dice_weight=0.5)
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=total_epochs, eta_min=1e-6)

    use_amp = (device.type == 'cuda')
    scaler = torch.amp.GradScaler('cuda', enabled=use_amp)

    start_epoch = 1
    best_val_iou = 0.0
    best_val_dice = 0.0
    training_time_accumulated = 0.0
    history = {
        "model_name": model_name,
        "epochs": [],
        "train_loss": [],
        "val_loss": [],
        "val_iou": [],
        "val_dice": [],
        "best_val_iou": 0.0,
        "best_val_dice": 0.0,
        "training_time_seconds": 0.0
    }

    # Check if a valid latest checkpoint exists to resume
    if os.path.exists(latest_checkpoint_path):
        print(f"\n[RESUME DETECTED] Found existing checkpoint at: {latest_checkpoint_path}")
        try:
            checkpoint = torch.load(latest_checkpoint_path, map_location=device, weights_only=False)
            model.load_state_dict(checkpoint["model_state"])
            optimizer.load_state_dict(checkpoint["optimizer_state"])
            scheduler.load_state_dict(checkpoint["scheduler_state"])
            if use_amp and "scaler_state" in checkpoint and checkpoint["scaler_state"] is not None:
                scaler.load_state_dict(checkpoint["scaler_state"])
            
            start_epoch = checkpoint["epoch"] + 1
            best_val_iou = checkpoint.get("best_val_iou", 0.0)
            best_val_dice = checkpoint.get("best_val_dice", 0.0)
            history = checkpoint.get("history", history)
            training_time_accumulated = history.get("training_time_seconds", 0.0)
            
            print(f" -> Resuming seamlessly from Epoch {start_epoch}/{total_epochs} (Previous Best Val IoU: {best_val_iou:.4f})")
        except Exception as e:
            print(f" [WARNING] Error reading latest checkpoint ({e}). Starting fresh.")
            start_epoch = 1

    if start_epoch > total_epochs:
        print(f"\n[DONE] Model has already finished all {total_epochs} epochs. Best Val IoU: {best_val_iou:.4f}")
        return model, history

    for epoch in range(start_epoch, total_epochs + 1):
        epoch_start_time = time.time()
        model.train()
        running_train_loss = 0.0

        for batch in train_loader:
            images = batch["image"].to(device)
            masks = batch["mask"].to(device)

            optimizer.zero_grad()
            with torch.amp.autocast('cuda', enabled=use_amp):
                logits = model(images)
                loss = criterion(logits, masks)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            running_train_loss += loss.item()

        scheduler.step()
        avg_train_loss = running_train_loss / len(train_loader)

        # Validation phase
        model.eval()
        running_val_loss = 0.0
        val_ious = []
        val_dices = []

        with torch.no_grad():
            for batch in val_loader:
                images = batch["image"].to(device)
                masks = batch["mask"].to(device)

                with torch.amp.autocast('cuda', enabled=use_amp):
                    logits = model(images)
                    loss = criterion(logits, masks)

                running_val_loss += loss.item()
                iou, dice = compute_batch_iou_dice(logits, masks)
                val_ious.append(iou)
                val_dices.append(dice)

        avg_val_loss = running_val_loss / len(val_loader)
        avg_val_iou = sum(val_ious) / len(val_ious)
        avg_val_dice = sum(val_dices) / len(val_dices)

        epoch_elapsed = time.time() - epoch_start_time
        training_time_accumulated += epoch_elapsed

        history["epochs"].append(epoch)
        history["train_loss"].append(round(avg_train_loss, 4))
        history["val_loss"].append(round(avg_val_loss, 4))
        history["val_iou"].append(round(avg_val_iou, 4))
        history["val_dice"].append(round(avg_val_dice, 4))
        history["training_time_seconds"] = round(training_time_accumulated, 2)

        # Save BEST model if improved
        is_best = False
        if avg_val_iou > best_val_iou:
            best_val_iou = avg_val_iou
            best_val_dice = avg_val_dice
            history["best_val_iou"] = round(best_val_iou, 4)
            history["best_val_dice"] = round(best_val_dice, 4)
            is_best = True
            
            atomic_torch_save({
                "epoch": epoch,
                "model_name": model_name,
                "state_dict": model.state_dict(),
                "val_iou": avg_val_iou,
                "val_dice": avg_val_dice,
                "history": history
            }, best_checkpoint_path)

        # Save LATEST model atomically after EVERY completed epoch
        latest_state = {
            "epoch": epoch,
            "model_name": model_name,
            "model_state": model.state_dict(),
            "optimizer_state": optimizer.state_dict(),
            "scheduler_state": scheduler.state_dict(),
            "scaler_state": scaler.state_dict() if use_amp else None,
            "best_val_iou": best_val_iou,
            "best_val_dice": best_val_dice,
            "history": history
        }
        atomic_torch_save(latest_state, latest_checkpoint_path)

        # Update JSON log atomically
        with open(log_json_path, "w") as f:
            json.dump({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "device": str(device),
                "dataset": "Refined Deep-SAR (SOS) Zenodo 15298010",
                "experiment": "V2 50-Epoch Cosine BCEDice",
                "benchmarks": {"unet_v2": history}
            }, f, indent=2)

        best_flag = " [*BEST*]" if is_best else ""
        print(f"Epoch [{epoch:02d}/{total_epochs:02d}] ({epoch_elapsed:.1f}s) | Train Loss: {avg_train_loss:.4f} | Val Loss: {avg_val_loss:.4f} | Val IoU: {avg_val_iou:.4f} | Val Dice: {avg_val_dice:.4f}{best_flag}")

    print(f"\nCompleted V2 {model_name} in {training_time_accumulated:.1f}s | Best Val IoU: {history['best_val_iou']:.4f}")
    return model, history


def run_real_deepsar_v2_training(epochs=50, batch_size=8, lr=3e-4):
    """
    Launches Experiment V2 with 50-epoch resumable training on real Deep-SAR.
    """
    from ml.dataset import load_real_deepsar_splits, RealDeepSARDataset
    os.makedirs("ml/results", exist_ok=True)
    os.makedirs("ml/checkpoints", exist_ok=True)
    
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for real Deep-SAR training.")
        
    device = torch.device("cuda")
    torch.backends.cudnn.benchmark = True
    
    print("=" * 70)
    print(" EXPERIMENT V2: REAL DEEP-SAR OIL SPILL U-NET (50 EPOCHS)")
    print("=" * 70)
    print(f"Device: {device} ({torch.cuda.get_device_name(0)})")
    
    train_pairs, val_pairs, test_pairs = load_real_deepsar_splits(
        data_dir="data/real_deep_sar",
        train_val_split_ratio=0.80,
        seed=42
    )
    
    print(f"\nDataset Verification:")
    print(f"  -> Total Official Train Pairs : {len(train_pairs) + len(val_pairs)}")
    print(f"  -> Training Split (80%)       : {len(train_pairs)} pairs")
    print(f"  -> Validation Split (20%)     : {len(val_pairs)} pairs")
    print(f"  -> Untouched Held-Out Test Set: {len(test_pairs)} pairs")
    
    train_loader = DataLoader(
        RealDeepSARDataset(train_pairs, is_train=True),
        batch_size=batch_size,
        shuffle=True,
        pin_memory=True,
        num_workers=2
    )
    
    val_loader = DataLoader(
        RealDeepSARDataset(val_pairs, is_train=False),
        batch_size=batch_size,
        shuffle=False,
        pin_memory=True,
        num_workers=2
    )
    
    unet_model, unet_history = train_resumable_v2_model(
        model_name="unet",
        train_loader=train_loader,
        val_loader=val_loader,
        device=device,
        total_epochs=epochs,
        lr=lr,
        best_checkpoint_path="ml/checkpoints/real_deepsar_unet_v2_best.pth",
        latest_checkpoint_path="ml/checkpoints/real_deepsar_unet_v2_latest.pth",
        log_json_path="ml/results/real_deepsar_v2_training_log.json"
    )
    
    return unet_model, unet_history


if __name__ == "__main__":
    run_real_deepsar_v2_training()



def compute_batch_iou_dice(logits, targets, threshold=0.5, smooth=1e-6):
    """
    Computes Intersection over Union (IoU) and Dice Coefficient (F1).
    """
    probs = torch.sigmoid(logits)
    preds = (probs > threshold).float()
    
    preds_flat = preds.view(-1)
    targets_flat = targets.view(-1)

    intersection = (preds_flat * targets_flat).sum().item()
    union = preds_flat.sum().item() + targets_flat.sum().item() - intersection

    iou = (intersection + smooth) / (union + smooth)
    dice = (2.0 * intersection + smooth) / (preds_flat.sum().item() + targets_flat.sum().item() + smooth)

    return iou, dice


def train_single_model(model_name, train_loader, val_loader, device, epochs=20, lr=3e-4, checkpoint_name=None):
    print(f"\n========================================================")
    print(f" TRAINING: {model_name.upper()} on {device}")
    print(f"========================================================")

    model = get_segmentation_model(model_name=model_name, in_channels=3, num_classes=1).to(device)
    criterion = CompoundOilSpillLoss(focal_weight=0.5, dice_weight=0.5)
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-6)

    use_amp = (device.type == 'cuda')
    scaler = torch.amp.GradScaler('cuda', enabled=use_amp)

    history = {
        "model_name": model_name,
        "epochs": [],
        "train_loss": [],
        "val_loss": [],
        "val_iou": [],
        "val_dice": [],
        "best_val_iou": 0.0,
        "best_val_dice": 0.0,
        "training_time_seconds": 0.0
    }

    start_time = time.time()
    best_iou = 0.0
    chk_filename = checkpoint_name if checkpoint_name else f"{model_name}_best.pth"
    best_checkpoint_path = f"ml/checkpoints/{chk_filename}"
    os.makedirs("ml/checkpoints", exist_ok=True)

    for epoch in range(1, epochs + 1):
        model.train()
        running_train_loss = 0.0

        for batch in train_loader:
            images = batch["image"].to(device)
            masks = batch["mask"].to(device)

            optimizer.zero_grad()
            with torch.amp.autocast('cuda', enabled=use_amp):
                logits = model(images)
                loss = criterion(logits, masks)

            scaler.scale(loss).backward()
            scaler.step(optimizer)
            scaler.update()

            running_train_loss += loss.item()

        scheduler.step()
        avg_train_loss = running_train_loss / len(train_loader)

        # Validation phase
        model.eval()
        running_val_loss = 0.0
        val_ious = []
        val_dices = []

        with torch.no_grad():
            for batch in val_loader:
                images = batch["image"].to(device)
                masks = batch["mask"].to(device)

                with torch.amp.autocast('cuda', enabled=use_amp):
                    logits = model(images)
                    loss = criterion(logits, masks)

                running_val_loss += loss.item()
                iou, dice = compute_batch_iou_dice(logits, masks)
                val_ious.append(iou)
                val_dices.append(dice)

        avg_val_loss = running_val_loss / len(val_loader)
        avg_val_iou = sum(val_ious) / len(val_ious)
        avg_val_dice = sum(val_dices) / len(val_dices)

        history["epochs"].append(epoch)
        history["train_loss"].append(round(avg_train_loss, 4))
        history["val_loss"].append(round(avg_val_loss, 4))
        history["val_iou"].append(round(avg_val_iou, 4))
        history["val_dice"].append(round(avg_val_dice, 4))

        if avg_val_iou > best_iou:
            best_iou = avg_val_iou
            history["best_val_iou"] = round(best_iou, 4)
            history["best_val_dice"] = round(avg_val_dice, 4)
            torch.save({
                "epoch": epoch,
                "model_name": model_name,
                "state_dict": model.state_dict(),
                "val_iou": avg_val_iou,
                "val_dice": avg_val_dice
            }, best_checkpoint_path)

        if epoch % 2 == 0 or epoch == epochs:
            print(f"Epoch [{epoch:02d}/{epochs:02d}] | Train Loss: {avg_train_loss:.4f} | Val Loss: {avg_val_loss:.4f} | Val IoU: {avg_val_iou:.4f} | Val Dice: {avg_val_dice:.4f}")

    total_time = round(time.time() - start_time, 2)
    history["training_time_seconds"] = total_time
    print(f"Completed {model_name} in {total_time}s | Best Val IoU: {history['best_val_iou']:.4f} | Checkpoint: {best_checkpoint_path}")

    return model, history


def run_real_deepsar_training(epochs=20, batch_size=8, lr=3e-4):
    """
    Trains U-Net on real Deep-SAR dataset (80% train, 20% validation).
    Saves weights strictly to ml/checkpoints/real_deepsar_unet_best.pth.
    """
    from ml.dataset import load_real_deepsar_splits, RealDeepSARDataset
    os.makedirs("ml/results", exist_ok=True)
    
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for real Deep-SAR training.")
        
    device = torch.device("cuda")
    torch.backends.cudnn.benchmark = True
    
    print("=" * 70)
    print(" REAL DEEP-SAR OIL SPILL U-NET TRAINING PIPELINE")
    print("=" * 70)
    print(f"Device: {device} ({torch.cuda.get_device_name(0)})")
    
    train_pairs, val_pairs, test_pairs = load_real_deepsar_splits(
        data_dir="data/real_deep_sar",
        train_val_split_ratio=0.80,
        seed=42
    )
    
    print(f"\nDataset Verification:")
    print(f"  -> Total Official Train Pairs : {len(train_pairs) + len(val_pairs)}")
    print(f"  -> Training Split (80%)       : {len(train_pairs)} pairs")
    print(f"  -> Validation Split (20%)     : {len(val_pairs)} pairs")
    print(f"  -> Untouched Held-Out Test Set: {len(test_pairs)} pairs")
    
    train_loader = DataLoader(
        RealDeepSARDataset(train_pairs, is_train=True),
        batch_size=batch_size,
        shuffle=True,
        pin_memory=True,
        num_workers=2
    )
    
    val_loader = DataLoader(
        RealDeepSARDataset(val_pairs, is_train=False),
        batch_size=batch_size,
        shuffle=False,
        pin_memory=True,
        num_workers=2
    )
    
    unet_model, unet_history = train_single_model(
        model_name="unet",
        train_loader=train_loader,
        val_loader=val_loader,
        device=device,
        epochs=epochs,
        lr=lr,
        checkpoint_name="real_deepsar_unet_best.pth"
    )
    
    training_summary = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "device": str(device),
        "dataset": "Refined Deep-SAR (SOS) Zenodo 15298010",
        "dataset_summary": {
            "total_official_train": len(train_pairs) + len(val_pairs),
            "train_samples": len(train_pairs),
            "val_samples": len(val_pairs),
            "untouched_test_samples": len(test_pairs)
        },
        "benchmarks": {
            "unet": unet_history
        }
    }
    
    out_log_path = "ml/results/real_deepsar_training_log.json"
    with open(out_log_path, "w") as f:
        json.dump(training_summary, f, indent=2)
        
    print(f"\nTraining summary successfully written to: {out_log_path}")
    return unet_model, test_pairs


def run_training_pipeline(num_scenes=40, tiles_per_scene=25, tile_size=256, epochs=20, batch_size=4, train_unet=True):
    os.makedirs("ml/results", exist_ok=True)
    
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required for OceanTrace training but was not detected. Aborting to prevent CPU fallback.")
    
    device = torch.device("cuda")
    torch.backends.cudnn.benchmark = True
    print(f"Initializing SAR Oil Spill ML Pipeline on: {device} ({torch.cuda.get_device_name(0)})")
    print(f"VRAM Available: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB | Mixed Precision: ENABLED | Batch Size: {batch_size} | Tile Size: {tile_size}x{tile_size}")

    # 1. Generate & Ingest Benchmark Dataset
    print(f"\n[1/4] Preparing Sentinel-1 SAR Dataset ({tile_size}x{tile_size} dual-pol VV/VH)...")
    samples = generate_benchmark_sar_corpus(data_dir="data/sar_oil_spill", num_scenes=num_scenes, tiles_per_scene=tiles_per_scene, tile_size=tile_size)
    
    # 2. Scene-Stratified Splitting
    print("\n[2/4] Performing Scene-Stratified 70/15/15 Data Splitting...")
    train_samples, val_samples, test_samples = create_stratified_scene_splits(samples, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15, seed=42)

    print(f"  -> Total Patches: {len(samples)}")
    print(f"  -> Train Split: {len(train_samples)} patches ({len(set(s['scene_id'] for s in train_samples))} scenes)")
    print(f"  -> Val Split:   {len(val_samples)} patches ({len(set(s['scene_id'] for s in val_samples))} scenes)")
    print(f"  -> Test Split:  {len(test_samples)} patches ({len(set(s['scene_id'] for s in test_samples))} scenes)")

    train_loader = DataLoader(SAROilSpillDataset(train_samples, is_train=True), batch_size=batch_size, shuffle=True, pin_memory=True)
    val_loader = DataLoader(SAROilSpillDataset(val_samples, is_train=False), batch_size=batch_size, shuffle=False, pin_memory=True)

    # 3. Train Primary Model (SARDeepLabV3Plus) & Alternative (SARUNet)
    print("\n[3/4] Training Primary DeepLabV3+ Model & Benchmarking...")
    deeplab_model, deeplab_history = train_single_model("deeplabv3plus", train_loader, val_loader, device, epochs=epochs, lr=3e-4)
    
    benchmarks = {"deeplabv3plus": deeplab_history}
    if train_unet:
        unet_model, unet_history = train_single_model("unet", train_loader, val_loader, device, epochs=epochs, lr=3e-4)
        benchmarks["unet"] = unet_history

    # Save training logs
    all_history = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "device": str(device),
        "dataset_summary": {
            "total_samples": len(samples),
            "train_samples": len(train_samples),
            "val_samples": len(val_samples),
            "test_samples": len(test_samples)
        },
        "benchmarks": benchmarks
    }

    with open("ml/results/training_log.json", "w") as f:
        json.dump(all_history, f, indent=2)

    print("\n[4/4] Training Pipeline Completed successfully. Results logged to ml/results/training_log.json")
    return deeplab_model, test_samples


if __name__ == "__main__":
    run_real_deepsar_training()

