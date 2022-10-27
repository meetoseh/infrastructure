#!/usr/bin/env bash
cd /usr/local/src/webapp
source /home/ec2-user/config.sh
bash scripts/auto/stop.sh
bash scripts/auto/before_install.sh
git pull origin main
bash scripts/auto/after_install.sh
bash scripts/auto/start.sh
