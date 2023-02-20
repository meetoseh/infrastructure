#!/usr/bin/env bash
crontab -l > cron
sed -i '/@reboot sudo nginx/d' cron
sed -i '/@daily sudo bash /home/ec2-user/reboot_nginx.sh/d' cron
crontab cron
rm cron

rm /home/ec2-user/reboot_nginx.sh

nginx -s quit
rm -rf /home/ec2-user/logs
rm -rf /var/cache/nginx
