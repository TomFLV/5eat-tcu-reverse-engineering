#!/bin/bash
# Exercise both channels of the CANtact Pro and report what each one does.
#
# WHAT THIS CAN AND CANNOT TELL YOU.
#
# A lone CAN node cannot successfully transmit even when the bus is perfectly
# terminated: every frame needs an acknowledge bit from another node, and with
# nobody listening the frame is retried and errors accumulate regardless. So "the
# frame did not go out" is not evidence of a termination fault, and no software
# test can separate those two on its own.
#
# What IS worth doing:
#
#   loopback mode proves the controller silicon and the driver work with the wiring
#   taken out of the question - the frame never leaves the chip.
#
#   a real transmit on each channel, with the error counters read before and after,
#   shows whether the two channels behave the SAME. They should. A channel that
#   errors differently from its twin is telling you something about how it is wired,
#   even if it cannot say what.
#
# TWO MISTAKES THIS SCRIPT USED TO MAKE, both of which would have misled at a bench:
#
#   It reported "transmit error counter: 0 -> 0" by grepping for berr-counter, which
#   gs_usb does not report. The grep matched nothing and the shell defaulted it to
#   zero, so a number that was never measured was printed as a measurement. It now
#   reads the counters this driver DOES report - bus-errors, error-warn, error-pass,
#   bus-off - and says so explicitly when a figure is unavailable.
#
#   It left the interface in loopback for the "real" transmit. Bringing a link up
#   again does not clear that flag; it needs `loopback off`. So the second half of
#   the test was still looping frames inside the chip and reporting them as sent.
#
# The definitive termination check is a multimeter across CANH and CANL with
# everything powered off: 60 ohms is a correctly terminated bus (two 120s in
# parallel), 120 ohms is one terminator, open circuit is none.
set -u

BITRATE=${BITRATE:-500000}

counters() {
    # gs_usb reports these; it does not report berr-counter.
    ip -details -statistics link show "$1" 2>/dev/null | awk '
        /re-started bus-errors/ { getline; print "      re-started="$1" bus-errors="$2 \
            " arbit-lost="$3" error-warn="$4" error-pass="$5" bus-off="$6 }'
}

txstats() {
    ip -statistics link show "$1" 2>/dev/null | awk '
        /TX:/ { getline; print "      tx packets="$2" errors="$3" dropped="$4 }'
}

state() {
    ip -details link show "$1" 2>/dev/null | grep -oP 'can (<[A-Z-]+> )?state \K[A-Z-]+'
}

mode() {
    if ip -details link show "$1" 2>/dev/null | grep -q "<LOOPBACK>"; then
        echo "LOOPBACK"
    else
        echo "normal"
    fi
}

for ch in can0 can1; do
    echo "=== $ch"
    if ! ip link show "$ch" >/dev/null 2>&1; then
        echo "    does not exist"
        continue
    fi

    # --- loopback: the controller talking to itself, no wiring involved -------
    ip link set "$ch" down 2>/dev/null
    if ip link set "$ch" up type can bitrate "$BITRATE" loopback on 2>/dev/null; then
        rm -f "/tmp/lb_$ch.txt"
        timeout 3 candump -n 1 "$ch" > "/tmp/lb_$ch.txt" 2>&1 &
        sleep 0.4
        cansend "$ch" '7E1#02A8000000000000' 2>/dev/null
        wait 2>/dev/null || true
        if grep -q "7E1" "/tmp/lb_$ch.txt" 2>/dev/null; then
            echo "    loopback   PASS - controller and driver work"
        else
            echo "    loopback   FAIL - nothing came back inside the chip"
        fi
    else
        echo "    loopback   could not configure"
    fi

    # --- real transmit -------------------------------------------------------
    # loopback off is required. Without it the flag persists and the "real"
    # transmit below is still looping inside the controller.
    ip link set "$ch" down 2>/dev/null
    ip link set "$ch" up type can bitrate "$BITRATE" loopback off 2>/dev/null
    echo "    mode now   $(mode "$ch")   state $(state "$ch")"
    echo "    before:"
    counters "$ch"; txstats "$ch"
    for _ in 1 2 3 4 5; do cansend "$ch" '7E1#02A8000000000000' 2>/dev/null; done
    sleep 1
    echo "    after five transmits:"
    counters "$ch"; txstats "$ch"
    echo "    state      $(state "$ch")"
    echo
done

echo "Reading the result:"
echo "  Both channels loopback PASS -> the adapter and driver are healthy."
echo "  With nothing else on the bus, errors and a state of ERROR-PASSIVE or"
echo "  BUS-OFF are EXPECTED: there is nobody to acknowledge a frame. That is not"
echo "  evidence of a termination fault."
echo "  The two channels behaving DIFFERENTLY is the thing worth looking at."
echo
echo "A LIMIT OF THIS ADAPTER, measured rather than assumed: gs_usb rejects"
echo "  berr-reporting on both channels, and does not report berr-counter. So"
echo "  bus-level error detail is unavailable here whatever you do - five"
echo "  transmits into an unterminated, unpopulated bus leave every counter at"
echo "  zero and the state at ERROR-ACTIVE. Absence of reported errors from this"
echo "  driver is not evidence that the bus is healthy."
echo
echo "For termination itself, use a multimeter across CANH and CANL, powered off:"
echo "  60 ohms  = two terminators, a correctly terminated bus"
echo "  120 ohms = one terminator"
echo "  open     = none"
