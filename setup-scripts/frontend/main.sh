#!/usr/bin/env bash
bash shared/wait_boot_finished.sh
echo "Frontend install started!"

# install nginx
mv nginx.repo /etc/yum.repos.d/nginx.repo
chmod +x reboot_nginx.sh
mv reboot_nginx.sh /home/ec2-user/reboot_nginx.sh
sudo -u ec2-user mkdir -p /home/ec2-user/logs

yum clean metadata
yum update -y
yum install -y nginx
nginx -t && nginx
nginx -s quit

# setup nginx config
mv nginx.conf /etc/nginx/nginx.conf
rm -rf /var/www
mv www/ /var/www/
chown nginx:nginx /var/www
chmod 755 /var/www

mkdir -p /var/cache/nginx
chown nginx:nginx /var/cache/nginx
chmod 755 /var/cache/nginx

nginx -s reload
bash /home/ec2-user/reboot_nginx.sh

# keep nginx running
cd /home/ec2-user
sudo crontab -l > cron
echo "@daily sudo bash /home/ec2-user/reboot_nginx.sh" >> cron
echo "@reboot sudo nginx" >> cron
sudo crontab cron
rm cron
