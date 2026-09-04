#!/bin/sh
# Usage: run /inyect/experiments/head/head.sh -LINE_COUNT FILE
# MesaOS substitutes $1 and $2 before executing each line.
write /tmp/head.lines $1
write /tmp/head.path $2
exec /inyect/experiments/head/head.elf
