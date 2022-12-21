#!/usr/bin/env bash
cd /usr/local/src/webapp
source /home/ec2-user/config.sh
bash scripts/auto/stop.sh
bash scripts/auto/before_install.sh
git pull origin main
if [ -f ".gitattributes" ]
then
    bash -c "/home/ec2-user/ensure_git_lfs.sh"
    git lfs pull
fi
bash scripts/auto/after_install.sh
bash scripts/auto/start.sh
