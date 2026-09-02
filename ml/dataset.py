import os
import glob
import math
import random
import numpy as np
from PIL import Image

try:
    import torch
    from torch.utils.data import Dataset, DataLoader
except ImportError:
    torch = None
    Dataset = object
    DataLoader = None


def normalize_sar_db(val_db, min_db=-30.0, max_db=0.0):
    """Normalize SAR backscatter in dB to [0, 1]."""
    clipped = np.clip(val_db, min_db, max_db)
    return (clipped - min_db) / (max_db - min_db)


class SAROilSpillDataset(Dataset):
    """
    Sentinel-1 SAR Oil Spill & Lookalike Semantic Segmentation Dataset.
    Expects 3-channel input tensors [VV_norm, VH_norm, (VV-VH)_norm] and binary masks [0, 1].
    """
    def __init__(self, sample_list, is_train=True, image_size=(256, 256)):
        self.samples = sample_list
        self.is_train = is_train
        self.image_size = image_size

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        item = self.samples[idx]
        image = item["image"]  # shape (H, W, 3) float32 in [0, 1]
        mask = item["mask"]    # shape (H, W) float32 in {0.0, 1.0}
        
        # Apply augmentations if training
        if self.is_train:
            # Random Horizontal Flip
            if random.random() > 0.5:
                image = np.fliplr(image)
                mask = np.fliplr(mask)
            # Random Vertical Flip
            if random.random() > 0.5:
                image = np.flipud(image)
                mask = np.flipud(mask)
            # Random 90-degree rotations
            k = random.randint(0, 3)
            if k > 0:
                image = np.rot90(image, k)
                mask = np.rot90(mask, k)
            # Random speckle/Gaussian noise injection
            if random.random() > 0.5:
                noise = np.random.normal(0, 0.015, image.shape).astype(np.float32)
                image = np.clip(image + noise, 0.0, 1.0)

        # Convert to channels-first PyTorch tensor
        image_t = torch.from_numpy(np.ascontiguousarray(image).transpose(2, 0, 1)).float()
        mask_t = torch.from_numpy(np.ascontiguousarray(mask)).unsqueeze(0).float()

        return {
            "image": image_t,
            "mask": mask_t,
            "scene_id": item.get("scene_id", "S1A_SCENE"),
            "has_slick": item.get("has_slick", float(mask.max() > 0.5))
        }


def generate_benchmark_sar_corpus(data_dir="data/sar_oil_spill", num_scenes=40, tiles_per_scene=25, tile_size=256):
    """
    Prepares a benchmark Sentinel-1 SAR oil-spill & lookalike dataset.
    Generates realistic C-band SAR scenes with dual-polarization (VV/VH) radar backscatter,
    oil spill dark-slick dampening physics, lookalike low-wind features, and vessel point reflectors.
    """
    os.makedirs(os.path.join(data_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "masks"), exist_ok=True)

    np.random.seed(42)
    random.seed(42)

    samples = []
    
    for s_idx in range(num_scenes):
        scene_id = f"S1A_202608{s_idx+1:02d}_{1000+s_idx:04d}"
        has_oil_in_scene = (s_idx % 3 != 0)  # 2/3 of scenes have oil spills, 1/3 are lookalikes/clean sea
        
        for t_idx in range(tiles_per_scene):
            tile_name = f"{scene_id}_tile_{t_idx:03d}"
            img_path = os.path.join(data_dir, "images", f"{tile_name}.npy")
            mask_path = os.path.join(data_dir, "masks", f"{tile_name}.png")

            # Simulate ocean surface backscatter (VV typically -15 dB to -8 dB, VH -25 dB to -18 dB)
            base_vv_db = np.random.normal(-12.0, 2.0, (tile_size, tile_size)).astype(np.float32)
            base_vh_db = base_vv_db - np.random.normal(7.0, 1.0, (tile_size, tile_size)).astype(np.float32)
            
            mask = np.zeros((tile_size, tile_size), dtype=np.uint8)
            has_slick = False

            # Add oil slick or lookalike
            if has_oil_in_scene and (t_idx % 2 == 0):
                # Realistic elongated curved oil slick
                num_nodes = np.random.randint(4, 8)
                cx = np.random.randint(100, tile_size - 100)
                cy = np.random.randint(100, tile_size - 100)
                slick_len = np.random.randint(120, 280)
                angle = np.random.uniform(0, math.pi)

                # Draw continuous slick curve
                for step in range(slick_len):
                    px = int(cx + step * math.cos(angle) + 15 * math.sin(step * 0.05))
                    py = int(cy + step * math.sin(angle) + 15 * math.cos(step * 0.05))
                    radius = np.random.randint(6, 18)
                    if 0 <= px < tile_size and 0 <= py < tile_size:
                        y_min, y_max = max(0, py - radius), min(tile_size, py + radius + 1)
                        x_min, x_max = max(0, px - radius), min(tile_size, px + radius + 1)
                        mask[y_min:y_max, x_min:x_max] = 1

                # Oil dampening effect: -6 to -10 dB reduction in VV backscatter (dark patch)
                base_vv_db[mask == 1] -= np.random.uniform(7.0, 11.0)
                base_vh_db[mask == 1] -= np.random.uniform(4.0, 7.0)
                has_slick = True
            
            elif not has_oil_in_scene and (t_idx % 3 == 0):
                # Natural lookalike (diffuse calm-water wind shadow, no distinct sharp edge)
                lx, ly = np.random.randint(150, 350), np.random.randint(150, 350)
                yy, xx = np.ogrid[:tile_size, :tile_size]
                dist = ((xx - lx)**2 + (yy - ly)**2) / (120.0**2)
                calm_mask = dist < 1.0
                base_vv_db[calm_mask] -= np.random.uniform(3.0, 5.5)  # milder dampening than mineral oil
                # Ground truth mask remains 0 (Lookalike is negative ground truth)

            # Assemble 3 normalized channels [0, 1]
            vv_norm = normalize_sar_db(base_vv_db)
            vh_norm = normalize_sar_db(base_vh_db)
            diff_norm = np.clip((vv_norm - vh_norm + 0.5), 0.0, 1.0)
            
            stacked_image = np.stack([vv_norm, vh_norm, diff_norm], axis=-1).astype(np.float32)

            # Save arrays
            np.save(img_path, stacked_image)
            Image.fromarray(mask * 255).save(mask_path)

            samples.append({
                "scene_id": scene_id,
                "image": stacked_image,
                "mask": mask.astype(np.float32),
                "has_slick": 1.0 if has_slick else 0.0
            })

    return samples


def create_stratified_scene_splits(samples, train_ratio=0.70, val_ratio=0.15, test_ratio=0.15, seed=42):
    """
    Splits samples at the SCENE level to avoid spatial correlation / data leakage across patches.
    """
    random.seed(seed)
    scene_ids = sorted(list(set(s["scene_id"] for s in samples)))
    random.shuffle(scene_ids)

    n_total = len(scene_ids)
    n_train = int(n_total * train_ratio)
    n_val = int(n_total * val_ratio)

    train_scenes = set(scene_ids[:n_train])
    val_scenes = set(scene_ids[n_train:n_train + n_val])
    test_scenes = set(scene_ids[n_train + n_val:])

    train_samples = [s for s in samples if s["scene_id"] in train_scenes]
    val_samples = [s for s in samples if s["scene_id"] in val_scenes]
    test_samples = [s for s in samples if s["scene_id"] in test_scenes]

    return train_samples, val_samples, test_samples


class RealDeepSARDataset(Dataset):
    """
    Dataset loader for real Deep-SAR (SOS) Sentinel-1 and PALSAR images and binary segmentation masks.
    """
    def __init__(self, sample_pairs, is_train=True):
        self.sample_pairs = sample_pairs
        self.is_train = is_train

    def __len__(self):
        return len(self.sample_pairs)

    def __getitem__(self, idx):
        img_path, mask_path = self.sample_pairs[idx]
        
        with Image.open(img_path) as img:
            img_arr = np.array(img).astype(np.float32) / 255.0
            if img_arr.ndim == 2:
                img_arr = np.stack([img_arr, img_arr, img_arr], axis=-1)
            elif img_arr.ndim == 3 and img_arr.shape[2] == 4:
                img_arr = img_arr[:, :, :3]
                
        with Image.open(mask_path) as mask:
            mask_arr = np.array(mask).astype(np.float32)
            if mask_arr.ndim == 3:
                mask_arr = mask_arr[:, :, 0]
            # Standard binarization: >= 128 is oil spill, < 128 is background
            mask_arr = (mask_arr > 127).astype(np.float32)

        if self.is_train:
            # Random Horizontal Flip
            if random.random() > 0.5:
                img_arr = np.fliplr(img_arr)
                mask_arr = np.fliplr(mask_arr)
            # Random Vertical Flip
            if random.random() > 0.5:
                img_arr = np.flipud(img_arr)
                mask_arr = np.flipud(mask_arr)
            # Random 90-degree rotations
            k = random.randint(0, 3)
            if k > 0:
                img_arr = np.rot90(img_arr, k)
                mask_arr = np.rot90(mask_arr, k)
            # Subtle speckle noise
            if random.random() > 0.5:
                noise = np.random.normal(0, 0.015, img_arr.shape).astype(np.float32)
                img_arr = np.clip(img_arr + noise, 0.0, 1.0)

        img_t = torch.from_numpy(np.ascontiguousarray(img_arr).transpose(2, 0, 1)).float()
        mask_t = torch.from_numpy(np.ascontiguousarray(mask_arr)).unsqueeze(0).float()

        return {
            "image": img_t,
            "mask": mask_t,
            "filename": os.path.basename(img_path)
        }


def load_real_deepsar_splits(data_dir="data/real_deep_sar", train_val_split_ratio=0.80, seed=42):
    """
    Loads real Deep-SAR dataset and separates into:
    - Train set: 80% of official train (approx 5,164 pairs)
    - Val set: 20% of official train (approx 1,291 pairs)
    - Held-out Test set: 100% of official val (1,615 pairs) untouched
    """
    from pathlib import Path
    base_dir = Path(data_dir)
    img_train_dir = base_dir / "images" / "train"
    mask_train_dir = base_dir / "masks" / "train"
    img_val_dir = base_dir / "images" / "val"
    mask_val_dir = base_dir / "masks" / "val"

    # 1. Gather all official train pairs (6,455)
    train_pairs = []
    for ip in sorted(list(img_train_dir.glob("*.png"))):
        if not ip.name.startswith("._"):
            mp = mask_train_dir / ip.name
            if mp.exists():
                train_pairs.append((str(ip), str(mp)))

    # 2. Gather all official held-out test pairs (1,615)
    test_pairs = []
    for ip in sorted(list(img_val_dir.glob("*.png"))):
        if not ip.name.startswith("._"):
            mp = mask_val_dir / ip.name
            if mp.exists():
                test_pairs.append((str(ip), str(mp)))

    # Deterministic train/val shuffle
    random.seed(seed)
    random.shuffle(train_pairs)

    n_total_train = len(train_pairs)
    n_split_train = int(n_total_train * train_val_split_ratio)

    split_train = train_pairs[:n_split_train]
    split_val = train_pairs[n_split_train:]

    return split_train, split_val, test_pairs


def read_sar_tiff(file_path):
    """
    Reads a 2-channel Sentinel-1 SAR TIFF (VV + VH) reliably using tifffile or rasterio.
    Returns float32 array in shape (H, W, 2).
    """
    try:
        import tifffile
        arr = tifffile.imread(file_path)
    except Exception:
        try:
            import rasterio
            with rasterio.open(file_path) as src:
                arr = src.read()  # (C, H, W)
                arr = np.transpose(arr, (1, 2, 0))  # (H, W, C)
        except Exception as e:
            raise RuntimeError(f"Failed to read SAR TIFF at {file_path}: {e}")

    # Ensure array is float32
    arr = arr.astype(np.float32)

    # Standardize dimensions to (H, W, C)
    if arr.ndim == 2:
        # Single channel -> duplicate to 2 channels
        arr = np.stack([arr, arr], axis=-1)
    elif arr.ndim == 3 and arr.shape[0] in [2, 3] and arr.shape[2] not in [2, 3]:
        # (C, H, W) format -> transpose to (H, W, C)
        arr = np.transpose(arr, (1, 2, 0))

    if arr.shape[-1] > 2:
        arr = arr[:, :, :2]

    # Handle NaN and Inf safely
    if np.isnan(arr).any() or np.isinf(arr).any():
        nan_mask = np.isnan(arr) | np.isinf(arr)
        arr[nan_mask] = -15.0  # Safe ocean backscatter replacement

    return arr


def read_mask_tiff(file_path):
    """
    Reads a binary segmentation mask (0 or 1 / 255).
    Returns float32 array in shape (H, W) with binary values in {0.0, 1.0}.
    """
    try:
        import tifffile
        arr = tifffile.imread(file_path)
    except Exception:
        try:
            import rasterio
            with rasterio.open(file_path) as src:
                arr = src.read(1)
        except Exception:
            arr = np.array(Image.open(file_path))

    arr = np.squeeze(arr).astype(np.float32)
    if arr.ndim == 3:
        arr = arr[:, :, 0]

    # Binarize: values > 0 are considered oil spill foreground (1.0), else 0.0
    arr = (arr > 0.5).astype(np.float32)
    return arr


def verify_dataset_integrity(sample_pairs, expected_shape=(2048, 2048), expected_channels=2, sample_check_count=50):
    """
    Automated runtime validation for TIFF readability, dimensions, channel count,
    dtype, NaN/Inf detection, mask dimensions, mask values, and pairing.
    Raises ValueError if anything unexpected is discovered.
    """
    print(f"\n[DATA INTEGRITY CHECK] Verifying {len(sample_pairs)} image/mask pairs...")
    if len(sample_pairs) == 0:
        raise ValueError("Dataset is empty! No image/mask pairs found.")

    check_indices = set(range(min(10, len(sample_pairs))))
    if len(sample_pairs) > sample_check_count:
        check_indices.update(random.sample(range(len(sample_pairs)), sample_check_count))
    else:
        check_indices = range(len(sample_pairs))

    checked = 0
    for idx in check_indices:
        img_path, mask_path, category = sample_pairs[idx]
        
        # 1. Existence check
        if not os.path.exists(img_path):
            raise FileNotFoundError(f"Image not found: {img_path}")
        if not os.path.exists(mask_path):
            raise FileNotFoundError(f"Mask not found: {mask_path}")

        # 2. Filename match check
        img_base = os.path.splitext(os.path.basename(img_path))[0]
        mask_base = os.path.splitext(os.path.basename(mask_path))[0]
        if img_base != mask_base:
            raise ValueError(f"Filename mismatch: Image '{img_base}' != Mask '{mask_base}'")

        # 3. Read image and verify properties
        img_arr = read_sar_tiff(img_path)
        if img_arr.shape[:2] != expected_shape:
            raise ValueError(f"Image dimension mismatch at {img_path}: expected {expected_shape}, got {img_arr.shape[:2]}")
        if img_arr.shape[2] != expected_channels:
            raise ValueError(f"Image channel mismatch at {img_path}: expected {expected_channels}, got {img_arr.shape[2]}")
        if np.isnan(img_arr).any() or np.isinf(img_arr).any():
            raise ValueError(f"Image contains unhandled NaN/Inf values: {img_path}")

        # 4. Read mask and verify properties
        mask_arr = read_mask_tiff(mask_path)
        if mask_arr.shape != expected_shape:
            raise ValueError(f"Mask dimension mismatch at {mask_path}: expected {expected_shape}, got {mask_arr.shape}")
        
        unique_vals = np.unique(mask_arr)
        if not np.all(np.isin(unique_vals, [0.0, 1.0])):
            raise ValueError(f"Mask contains non-binary values {unique_vals} at {mask_path}")

        # 5. Category-specific validation
        if category in ["no_oil", "lookalike"]:
            if mask_arr.max() > 0.0:
                raise ValueError(f"Category '{category}' mask contains positive labels at {mask_path}")

        checked += 1

    print(f"[DATA INTEGRITY CHECK PASSED] All {checked} verified samples met all requirements (dimensions {expected_shape}, {expected_channels} channels, float32, binary masks, valid pairings).")


def compute_robust_sar_stats(sample_pairs, sample_count=30):
    """
    Computes robust data-derived SAR normalization parameters (1st and 99th percentiles)
    from a representative sample of dual-polarization scenes.
    """
    print(f"\n[CALIBRATION] Computing data-derived SAR statistics across {sample_count} scenes...")
    vv_vals = []
    vh_vals = []
    
    indices = random.sample(range(len(sample_pairs)), min(sample_count, len(sample_pairs)))
    for idx in indices:
        img_path = sample_pairs[idx][0]
        arr = read_sar_tiff(img_path)
        # subsample pixels for speed
        vv_sub = arr[::16, ::16, 0].flatten()
        vh_sub = arr[::16, ::16, 1].flatten()
        vv_vals.append(vv_sub)
        vh_vals.append(vh_sub)
        
    vv_all = np.concatenate(vv_vals)
    vh_all = np.concatenate(vh_vals)
    
    # Exclude non-finite
    vv_valid = vv_all[np.isfinite(vv_all)]
    vh_valid = vh_all[np.isfinite(vh_all)]
    
    vv_p1, vv_p99 = np.percentile(vv_valid, [1.0, 99.0])
    vh_p1, vh_p99 = np.percentile(vh_valid, [1.0, 99.0])
    
    stats = {
        "vv_min": float(vv_p1),
        "vv_max": float(vv_p99),
        "vh_min": float(vh_p1),
        "vh_max": float(vh_p99)
    }
    print(f" -> Data-derived VV range [1%, 99%]: [{stats['vv_min']:.2f}, {stats['vv_max']:.2f}]")
    print(f" -> Data-derived VH range [1%, 99%]: [{stats['vh_min']:.2f}, {stats['vh_max']:.2f}]")
    return stats


class DualPolSARSegmentationDataset(Dataset):
    """
    High-performance PyTorch Dataset for Sentinel-1 SAR scenes and binary masks.
    Defaults to in_channels=3 [VV, VH, VV-VH] (V4 formulation) with optional in_channels=2.
    Implements patch-first slicing for minimal memory and compute overhead.
    """
    def __init__(self, sample_pairs, is_train=True, crop_size=(512, 512), in_channels=3, norm_stats=None):
        self.samples = sample_pairs
        self.is_train = is_train
        self.crop_size = crop_size
        self.in_channels = in_channels
        self.norm_stats = norm_stats or {
            "vv_min": -31.62, "vv_max": -4.69,
            "vh_min": -35.63, "vh_max": -13.68,
            "diff_min": -2.0, "diff_max": 22.0
        }

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        img_path, mask_path, category = self.samples[idx]

        img_arr = read_sar_tiff(img_path)  # (H, W, 2)
        mask_arr = read_mask_tiff(mask_path)  # (H, W)

        h, w = img_arr.shape[:2]
        ch, cw = self.crop_size

        # PATCH-FIRST SLICING: Slice the target 512x512 window BEFORE applying normalization math
        if ch < h and cw < w:
            if self.is_train:
                has_slick = (mask_arr.max() > 0.5)
                if has_slick and random.random() < 0.5:
                    # Fast downsampled coordinate lookup (32x faster)
                    y_sub, x_sub = np.where(mask_arr[::8, ::8] > 0.5)
                    if len(y_sub) > 0:
                        c_idx = random.randint(0, len(y_sub) - 1)
                        cy, cx = y_sub[c_idx] * 8, x_sub[c_idx] * 8
                        y0 = max(0, min(h - ch, cy - ch // 2))
                        x0 = max(0, min(w - cw, cx - cw // 2))
                    else:
                        y0 = random.randint(0, h - ch)
                        x0 = random.randint(0, w - cw)
                else:
                    y0 = random.randint(0, h - ch)
                    x0 = random.randint(0, w - cw)
            else:
                y0 = (h - ch) // 2
                x0 = (w - cw) // 2

            img_patch = img_arr[y0:y0 + ch, x0:x0 + cw]
            mask_patch = mask_arr[y0:y0 + ch, x0:x0 + cw]
        else:
            img_patch = img_arr
            mask_patch = mask_arr

        # Data-derived Normalization applied directly to the sliced 512x512 patch
        vv_raw = img_patch[:, :, 0]
        vh_raw = img_patch[:, :, 1]

        vv_min, vv_max = self.norm_stats["vv_min"], self.norm_stats["vv_max"]
        vh_min, vh_max = self.norm_stats["vh_min"], self.norm_stats["vh_max"]

        vv_norm = np.clip((vv_raw - vv_min) / max(1e-5, (vv_max - vv_min)), 0.0, 1.0)
        vh_norm = np.clip((vh_raw - vh_min) / max(1e-5, (vh_max - vh_min)), 0.0, 1.0)

        if self.in_channels == 3:
            # Calibrate VV - VH polarization difference channel
            diff_raw = vv_raw - vh_raw
            d_min = self.norm_stats.get("diff_min", 0.0)
            d_max = self.norm_stats.get("diff_max", 20.0)
            diff_norm = np.clip((diff_raw - d_min) / max(1e-5, (d_max - d_min)), 0.0, 1.0)
            norm_img = np.stack([vv_norm, vh_norm, diff_norm], axis=-1)  # (512, 512, 3)
        else:
            norm_img = np.stack([vv_norm, vh_norm], axis=-1)  # (512, 512, 2)

        # Augmentations (Train only)
        if self.is_train:
            if random.random() > 0.5:
                norm_img = np.fliplr(norm_img)
                mask_patch = np.fliplr(mask_patch)
            if random.random() > 0.5:
                norm_img = np.flipud(norm_img)
                mask_patch = np.flipud(mask_patch)
            k = random.randint(0, 3)
            if k > 0:
                norm_img = np.rot90(norm_img, k)
                mask_patch = np.rot90(mask_patch, k)
            if random.random() > 0.5:
                noise = np.random.normal(0, 0.015, norm_img.shape).astype(np.float32)
                norm_img = np.clip(norm_img + noise, 0.0, 1.0)

        image_t = torch.from_numpy(np.ascontiguousarray(norm_img).transpose(2, 0, 1)).float()
        mask_t = torch.from_numpy(np.ascontiguousarray(mask_patch)).unsqueeze(0).float()

        return {
            "image": image_t,
            "mask": mask_t,
            "filename": os.path.basename(img_path),
            "category": category
        }


def create_dualpol_train_val_splits(sample_pairs, val_ratio=0.20, seed=42):
    """
    Creates a stratified, deterministic train/validation split preserving proportions
    of Part I Oil Spill, Part II No-Oil, and Part II Lookalike.
    """
    random.seed(seed)
    
    # Check if scene group identifiers can be parsed from filenames (e.g. S1A_... or scene ID)
    group_dict = {}
    can_group_by_scene = False
    for p in sample_pairs:
        fname = os.path.basename(p[0])
        parts = fname.split("_")
        if len(parts) >= 3 and (parts[0].startswith("S1") or parts[0].startswith("sentinel")):
            scene_id = "_".join(parts[:2])
            group_dict.setdefault(scene_id, []).append(p)
            can_group_by_scene = True

    if can_group_by_scene and len(group_dict) > 10:
        print(f"\n[DATA SPLIT] Group-level scene identifiers identified ({len(group_dict)} distinct scenes). Performing group-level stratified split.")
        train_pairs = []
        val_pairs = []
        scene_ids = list(group_dict.keys())
        random.shuffle(scene_ids)
        n_val = int(len(scene_ids) * val_ratio)
        val_scenes = set(scene_ids[:n_val])
        for s_id, items in group_dict.items():
            if s_id in val_scenes:
                val_pairs.extend(items)
            else:
                train_pairs.extend(items)
    else:
        print("\n[DATA SPLIT LIMITATION REPORT] Discrete multi-patch scene IDs not explicitly present in filename prefix. Applying deterministic stratified sample-level partitioning across Oil Spill, No-Oil, and Lookalike categories.")
        by_category = {"oil_spill": [], "no_oil": [], "lookalike": []}
        for item in sample_pairs:
            cat = item[2]
            by_category.setdefault(cat, []).append(item)

        train_pairs = []
        val_pairs = []

        for cat, items in by_category.items():
            sorted_items = sorted(items, key=lambda x: x[0])
            random.shuffle(sorted_items)
            n_val = int(len(sorted_items) * val_ratio)
            val_pairs.extend(sorted_items[:n_val])
            train_pairs.extend(sorted_items[n_val:])

    random.shuffle(train_pairs)
    random.shuffle(val_pairs)

    print(f" -> Total samples: {len(sample_pairs)}")
    print(f" -> Train: {len(train_pairs)} pairs")
    print(f" -> Val:   {len(val_pairs)} pairs")
    return train_pairs, val_pairs



