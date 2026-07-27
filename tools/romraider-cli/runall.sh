#!/bin/bash
DEF="$HOME/rrcli/5eat_tcu_romraider_defs.xml"
CP="$HOME/rrcli/out:$HOME/rrcli/i18n:$HOME/rrcli/lib/*"
for f in "$HOME/5eat/91D1206000_5EAT.bin" "$HOME/5eat/91FE216300.bin" "$HOME"/5eat/roms_extracted/*.bin; do
  case "$f" in *A3DE*) continue ;; esac
  java -cp "$CP" DefCheck "$DEF" "$f" 2>/dev/null | grep -v log4j
done
