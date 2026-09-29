#!/bin/bash
set -e

git clone https://github.com/FaronBracy/RogueSharp.git /tmp/repo
cd /tmp/repo
git checkout 22181573e2fcfbd350fbb80ea91c921b325b9524

mkdir -p /app
cp -a /tmp/repo/RogueSharp/. /app/
cd /app
rm -rf /tmp/repo

echo ': # C# library; the grader compiles the sources under /app' > ./setup.sh
