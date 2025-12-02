#!/bin/bash
SWAP_FILE="/swap"
SWAP_SIZE="2G"

if [ "$(sudo swapon -s | grep -o "$SWAP_FILE")" = "$SWAP_FILE" ]; then
    sudo swapoff "$SWAP_FILE"
fi
if [ ! -f "$SWAP_FILE" ]; then
    sudo fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
    sudo chmod 600 "$SWAP_FILE"
    sudo mkswap "$SWAP_FILE"
fi
sudo swapon "$SWAP_FILE"
if ! grep -q "$SWAP_FILE" /etc/fstab; then
    echo "$SWAP_FILE none swap sw 0 0" | sudo tee -a /etc/fstab
fi
