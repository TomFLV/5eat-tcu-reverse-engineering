#!/bin/bash
# Prepare WSL to talk to the CANtact Pro. Run this once, with sudo.
#
#   sudo bash tools/bench/setup-wsl-can.sh
#
# WHAT IS ALREADY TRUE on this machine, checked before writing this:
#
#   kernel 6.18.33.2-microsoft-standard-WSL2 has can, can_raw, can_dev, vcan,
#   gs_usb and slcan available as modules. Older WSL kernels shipped without the
#   CAN subsystem entirely, which no amount of USB forwarding fixes - it needed a
#   rebuilt kernel. This one does not.
#
# WHAT THIS DOES: installs the CAN userspace tools and the usbip client, loads the
# modules, and proves the subsystem works using a virtual interface - no hardware
# involved, so a failure here is a WSL problem and not a wiring problem.
#
# It does NOT attach the adapter. That is a Windows-side step: see
# tools/bench/attach-cantact.ps1, which needs usbipd-win and an admin prompt.
set -eu

echo "=== installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq can-utils python3-pip linux-tools-generic hwdata \
                      python3-venv >/dev/null
echo "  can-utils, python3-pip, usbip client installed"

echo
echo "=== loading the CAN modules"
for m in can can_raw can_dev vcan gs_usb; do
    modprobe "$m" 2>/dev/null && echo "  $m loaded" || echo "  $m FAILED to load"
done

echo
echo "=== proving the CAN stack works, with no hardware"
# vcan is a loopback CAN interface. If a frame sent on it comes back, the kernel's
# CAN support is real - which is worth knowing separately from whether the adapter
# is attached, because the two fail identically from the application's point of
# view.
ip link delete vcan0 2>/dev/null || true
ip link add dev vcan0 type vcan
ip link set up vcan0
timeout 3 candump -n 1 vcan0 > /tmp/vcan_test.txt 2>&1 &
sleep 0.5
cansend vcan0 '410#0000006400000000'
wait || true
if grep -q "410" /tmp/vcan_test.txt 2>/dev/null; then
    echo "  vcan0 loopback works:"
    sed 's/^/    /' /tmp/vcan_test.txt
else
    echo "  vcan0 loopback produced nothing - the CAN stack is not working"
    cat /tmp/vcan_test.txt 2>/dev/null | sed 's/^/    /'
fi

echo
echo "=== python-can"
pip3 install --quiet --break-system-packages python-can 2>/dev/null \
    || pip3 install --quiet python-can
python3 -c "import can; print('  python-can', can.__version__)"

echo
echo "=== done. Next, on the WINDOWS side:"
echo "    tools/bench/attach-cantact.ps1     (needs admin, installs usbipd-win)"
echo
echo "Then back here:  ip link show can0"
