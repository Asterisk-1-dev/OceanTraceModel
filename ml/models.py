import torch
import torch.nn as nn
import torch.nn.functional as F


class DiceLoss(nn.Module):
    """
    Dice Similarity Loss for extreme foreground class imbalance in SAR oil spill segmentation.
    """
    def __init__(self, smooth=1.0):
        super(DiceLoss, self).__init__()
        self.smooth = smooth

    def forward(self, logits, targets):
        probs = torch.sigmoid(logits)
        probs_flat = probs.view(-1)
        targets_flat = targets.view(-1)

        intersection = (probs_flat * targets_flat).sum()
        dice = (2.0 * intersection + self.smooth) / (probs_flat.sum() + targets_flat.sum() + self.smooth)
        return 1.0 - dice


class FocalLoss(nn.Module):
    """
    Binary Focal Loss to emphasize hard negative lookalikes and boundary pixels.
    """
    def __init__(self, alpha=0.25, gamma=2.0):
        super(FocalLoss, self).__init__()
        self.alpha = alpha
        self.gamma = gamma

    def forward(self, logits, targets):
        bce_loss = F.binary_cross_entropy_with_logits(logits, targets, reduction='none')
        probs = torch.sigmoid(logits)
        p_t = probs * targets + (1.0 - probs) * (1.0 - targets)
        alpha_factor = self.alpha * targets + (1.0 - self.alpha) * (1.0 - targets)
        modulating_factor = (1.0 - p_t) ** self.gamma
        focal_loss = alpha_factor * modulating_factor * bce_loss
        return focal_loss.mean()


class BCEDiceLoss(nn.Module):
    """
    Standard Binary Cross-Entropy + Dice Loss combination.
    """
    def __init__(self, bce_weight=0.5, dice_weight=0.5, smooth=1.0):
        super(BCEDiceLoss, self).__init__()
        self.bce = nn.BCEWithLogitsLoss()
        self.dice = DiceLoss(smooth=smooth)
        self.bce_weight = bce_weight
        self.dice_weight = dice_weight

    def forward(self, logits, targets):
        return self.bce_weight * self.bce(logits, targets) + self.dice_weight * self.dice(logits, targets)


class CompoundOilSpillLoss(nn.Module):
    """
    Hybrid Focal + Dice loss recommended in ADR-007.
    """
    def __init__(self, focal_weight=0.5, dice_weight=0.5):
        super(CompoundOilSpillLoss, self).__init__()
        self.focal = FocalLoss(alpha=0.25, gamma=2.0)
        self.dice = DiceLoss(smooth=1.0)
        self.focal_weight = focal_weight
        self.dice_weight = dice_weight

    def forward(self, logits, targets):
        return self.focal_weight * self.focal(logits, targets) + self.dice_weight * self.dice(logits, targets)




class DoubleConv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super(DoubleConv, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv2d(in_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True),
            nn.Conv2d(out_ch, out_ch, 3, padding=1, bias=False),
            nn.BatchNorm2d(out_ch),
            nn.ReLU(inplace=True)
        )

    def forward(self, x):
        return self.conv(x)


class SARUNet(nn.Module):
    """
    U-Net baseline architecture for SAR Oil Spill Segmentation.
    """
    def __init__(self, in_channels=3, num_classes=1, base_filters=32):
        super(SARUNet, self).__init__()
        self.inc = DoubleConv(in_channels, base_filters)
        self.down1 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters, base_filters * 2))
        self.down2 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters * 2, base_filters * 4))
        self.down3 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters * 4, base_filters * 8))
        self.down4 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters * 8, base_filters * 8))

        self.up1 = nn.ConvTranspose2d(base_filters * 8, base_filters * 4, 2, stride=2)
        # up1 output: base_filters*4; skip x4: base_filters*8 → cat = base_filters*12
        self.conv_up1 = DoubleConv(base_filters * 4 + base_filters * 8, base_filters * 4)

        self.up2 = nn.ConvTranspose2d(base_filters * 4, base_filters * 2, 2, stride=2)
        # up2 output: base_filters*2; skip x3: base_filters*4 → cat = base_filters*6
        self.conv_up2 = DoubleConv(base_filters * 2 + base_filters * 4, base_filters * 2)

        self.up3 = nn.ConvTranspose2d(base_filters * 2, base_filters, 2, stride=2)
        # up3 output: base_filters;   skip x2: base_filters*2 → cat = base_filters*3
        self.conv_up3 = DoubleConv(base_filters + base_filters * 2, base_filters)

        self.up4 = nn.ConvTranspose2d(base_filters, base_filters, 2, stride=2)
        # up4 output: base_filters;   skip x1: base_filters   → cat = base_filters*2 (unchanged)
        self.conv_up4 = DoubleConv(base_filters * 2, base_filters)

        self.outc = nn.Conv2d(base_filters, num_classes, 1)

    def forward(self, x):
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)

        x = self.up1(x5)
        x = self.conv_up1(torch.cat([x, x4], dim=1))

        x = self.up2(x)
        x = self.conv_up2(torch.cat([x, x3], dim=1))

        x = self.up3(x)
        x = self.conv_up3(torch.cat([x, x2], dim=1))

        x = self.up4(x)
        x = self.conv_up4(torch.cat([x, x1], dim=1))

        logits = self.outc(x)
        return logits


class ASPPConv(nn.Sequential):
    def __init__(self, in_channels, out_channels, dilation):
        super(ASPPConv, self).__init__(
            nn.Conv2d(in_channels, out_channels, 3, padding=dilation, dilation=dilation, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )


class ASPPPooling(nn.Sequential):
    def __init__(self, in_channels, out_channels):
        super(ASPPPooling, self).__init__(
            nn.AdaptiveAvgPool2d(1),
            nn.Conv2d(in_channels, out_channels, 1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True)
        )

    def forward(self, x):
        size = x.shape[-2:]
        for mod in self:
            x = mod(x)
        return F.interpolate(x, size=size, mode='bilinear', align_corners=False)


class ASPP(nn.Module):
    """
    Atrous Spatial Pyramid Pooling module for multi-scale ocean context.
    """
    def __init__(self, in_channels, atrous_rates=[6, 12, 18], out_channels=128):
        super(ASPP, self).__init__()
        modules = [
            nn.Sequential(
                nn.Conv2d(in_channels, out_channels, 1, bias=False),
                nn.BatchNorm2d(out_channels),
                nn.ReLU(inplace=True)
            )
        ]
        for rate in atrous_rates:
            modules.append(ASPPConv(in_channels, out_channels, rate))
        modules.append(ASPPPooling(in_channels, out_channels))

        self.convs = nn.ModuleList(modules)
        self.project = nn.Sequential(
            nn.Conv2d(len(modules) * out_channels, out_channels, 1, bias=False),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
            nn.Dropout(0.3)
        )

    def forward(self, x):
        res = [conv(x) for conv in self.convs]
        res = torch.cat(res, dim=1)
        return self.project(res)


class SARDeepLabV3Plus(nn.Module):
    """
    DeepLabV3+ architecture with ASPP module for SAR Oil Spill Detection.
    """
    def __init__(self, in_channels=3, num_classes=1, base_filters=32):
        super(SARDeepLabV3Plus, self).__init__()
        # Encoder (ResNet-style blocks)
        self.initial = DoubleConv(in_channels, base_filters)
        self.layer1 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters, base_filters * 2))
        self.layer2 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters * 2, base_filters * 4))
        self.layer3 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(base_filters * 4, base_filters * 8))

        # ASPP on deep features
        self.aspp = ASPP(in_channels=base_filters * 8, atrous_rates=[6, 12, 18], out_channels=base_filters * 4)

        # Low-level feature projection
        self.low_level_proj = nn.Sequential(
            nn.Conv2d(base_filters * 2, base_filters, 1, bias=False),
            nn.BatchNorm2d(base_filters),
            nn.ReLU(inplace=True)
        )

        # Decoder
        self.decoder = nn.Sequential(
            DoubleConv(base_filters * 4 + base_filters, base_filters * 2),
            nn.Conv2d(base_filters * 2, num_classes, 1)
        )

    def forward(self, x):
        input_size = x.shape[-2:]
        x0 = self.initial(x)
        low_level = self.layer1(x0)
        x2 = self.layer2(low_level)
        x3 = self.layer3(x2)

        aspp_out = self.aspp(x3)
        aspp_up = F.interpolate(aspp_out, size=low_level.shape[-2:], mode='bilinear', align_corners=False)

        low_proj = self.low_level_proj(low_level)
        dec_in = torch.cat([aspp_up, low_proj], dim=1)
        logits_low = self.decoder(dec_in)

        # Final upsample to original resolution
        logits = F.interpolate(logits_low, size=input_size, mode='bilinear', align_corners=False)
        return logits


def get_segmentation_model(model_name="deeplabv3plus", in_channels=3, num_classes=1):
    """
    Factory creating either SARDeepLabV3Plus or SARUNet.
    """
    name = model_name.lower().replace("-", "").replace("_", "")
    if "deeplab" in name:
        return SARDeepLabV3Plus(in_channels=in_channels, num_classes=num_classes)
    elif "unet" in name:
        return SARUNet(in_channels=in_channels, num_classes=num_classes)
    else:
        raise ValueError(f"Unknown architecture: {model_name}. Supported: 'unet', 'deeplabv3plus'")
