#!/usr/bin/env bash
install_redis() {
    yum -y install yum-utils
    yum -y install http://rpms.remirepo.net/enterprise/remi-release-7.rpm
    yum-config-manager --enable remi
    yum -y install redis
}

configure_redis() {
    source config.sh
    
    while screen -S redis -X stuff "^C"
    do
        sleep 1
    done

    while screen -S sent -X stuff "^C"
    do
        sleep 1
    done

    systemctl stop redis-sentinel

    mkdir -p /etc/redis
    mkdir -p /redis
    
    mv redis.conf /etc/redis/redis.conf
    if [ $MY_IP != $MAIN_IP ]
    then
        echo "replicaof $MAIN_IP 6379" >> /etc/redis/redis.conf
        echo "replica-serve-stale-data no" >> /etc/redis/redis.conf
        echo "replica-read-only yes" >> /etc/redis/redis.conf
        echo "replica-priority 100" >> /etc/redis/redis.conf
    fi

    mv sentinel.conf /etc/redis/sentinel.conf
    screen -dmS redis redis-server /etc/redis/redis.conf
    screen -dmS sent redis-sentinel /etc/redis/sentinel.conf

    crontab -l > cron
    sed -i '/@reboot sudo screen -dmS redis/d' cron
    sed -i '/@reboot sudo screen -dmS sent/d' cron
    echo "@reboot sudo screen -dmS redis redis-server /etc/redis/redis.conf" >> cron
    echo "@reboot sudo screen -dmS sent redis-sentinel /etc/redis/sentinel.conf" >> cron
    crontab cron
    rm cron     
}

bash shared/wait_boot_finished.sh
install_redis
configure_redis
