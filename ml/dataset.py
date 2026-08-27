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

