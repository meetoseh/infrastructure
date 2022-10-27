#!/usr/bin/env bash
bash shared/wait_boot_finished.sh
cp config.sh /home/ec2-user/config.sh
cp repo.sh /home/ec2-user/repo.sh
cp update_webapp.sh /home/ec2-user/update_webapp.sh
cd /usr/local/src
. /home/ec2-user/repo.sh
if [ ! -d webapp ]
then
    mkdir webapp
    cd webapp
    git init
    git remote add origin "https://${GITHUB_USERNAME}:${GITHUB_PAT}@github.com/${GITHUB_REPOSITORY}"
    git pull origin main
    bash -c "source /home/ec2-user/config.sh && bash scripts/auto/after_install.sh && bash scripts/auto/start.sh"
else
    bash /home/ec2-user/update_webapp.sh
fi
cd /home/ec2-user
crontab -l > cron
sed -i "/@reboot sudo bash -c 'cd \/usr\/local\/src\/webapp/d" cron
echo "@reboot sudo bash -c 'cd /usr/local/src/webapp && bash scripts/auto/start.sh'" >> cron
crontab cron
rm cron
