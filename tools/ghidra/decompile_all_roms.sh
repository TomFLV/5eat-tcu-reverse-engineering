#!/bin/bash
GH=~/ghidra_12.1.2_PUBLIC/support/analyzeHeadless
OUT=~/5eat/decomp_rw
cd ~
for f in ~/5eat/roms_extracted/*.bin ~/5eat/91D1206000_5EAT.bin ~/5eat/91FE216300.bin; do
  b=$(basename "$f" .bin)
  case "$b" in A3DE*) continue;; esac
  [ -f "$OUT/$b.c" ] && continue
  rm -rf ~/gp_rw; mkdir -p ~/gp_rw
  cp "$f" /tmp/t.bin
  $GH ~/gp_rw p -import /tmp/t.bin -processor 'm32r:2:default' -loader BinaryLoader -loader-baseAddr 0x0 -noanalysis >/dev/null 2>&1
  $GH ~/gp_rw p -process t.bin -noanalysis -scriptPath ~/my_scripts -postScript SeedAuto.java >/dev/null 2>&1
  sed -i "s|String outPath = .*|String outPath = \"$OUT/$b.c\";|" ~/my_scripts/DecompileAll.java
  $GH ~/gp_rw p -process t.bin -noanalysis -scriptPath ~/my_scripts -postScript DecompileAll.java 2>&1 | grep -oE 'Decompiled [0-9]+ functions OK, [0-9]+ failed' | sed "s|^|$b: |"
done
echo BATCH_DONE
