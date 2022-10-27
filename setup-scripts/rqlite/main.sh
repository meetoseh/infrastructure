#!/usr/bin/env bash
install_rqlite() {
    local latest_release_url=$(curl -L -s --retry 5 --retry-connrefused https://api.github.com/repos/rqlite/rqlite/releases/latest | jq -r ".assets[] | .browser_download_url" | grep -Eo "^.*rqlite-.*-linux-arm64.tar.gz")
    local fname=$(basename $latest_release_url)
    local foldername=$(basename $fname .tar.gz)
    local install_bin="/usr/bin"
    cd /usr/local/src
    rm -f $fname
    rm -rf $foldername
    wget "$latest_release_url"
    tar -xvf $fname

    echo "/usr/local/src/$foldername" >> /home/ec2-user/rqlite_uninstall.txt
    for binpath in $foldername/*
    do
        if ! echo $binpath | grep '*' > /dev/null
        then
            local binname=$(basename $binpath)
            chmod +x $binpath
            rm -f $install_bin/$binname
            ln -s $PWD/$binpath $install_bin/$binname
            chmod +x $install_bin/$binname
            echo "$install_bin/$binname" >> /home/ec2-user/rqlite_uninstall.txt
        fi
    done
}

start_rqlite_cluster() {
    source config.sh

    echo "#!/usr/bin/env bash" > /home/ec2-user/start_rqlited.sh

    if [ "$NODE_ID" = "$DEFAULT_LEADER_NODE_ID" ]
    then
        echo "rqlited -fk=true -node-id $NODE_ID -http-addr $MY_IP:4001 -raft-addr $MY_IP:4002 -on-disk /home/ec2-user/rqlite-data 2>&1 | tee -a /home/ec2-user/rqlite.log" >> /home/ec2-user/start_rqlited.sh
    else
        echo "rqlited -fk=true -node-id $NODE_ID -join $JOIN_ADDRESS -join-attempts 1000 -http-addr $MY_IP:4001 -raft-addr $MY_IP:4002 -on-disk /home/ec2-user/rqlite-data 2>&1 | tee -a /home/ec2-user/rqlite.log" >> /home/ec2-user/start_rqlited.sh
    fi
    chmod +x /home/ec2-user/start_rqlited.sh

    while screen -S rqlited -X stuff "^C"
    do
        sleep 1
    done

    # if we don't change directory it will slow screen -r
    bash -c "cd /home/ec2-user && screen -dmS rqlited /home/ec2-user/start_rqlited.sh"

    crontab -l > cron
    sed -i '/^@reboot sudo screen -dmS rqlited/d' cron
    echo "@reboot sudo screen -dmS rqlited /home/ec2-user/start_rqlited.sh" >> cron
    crontab cron
    rm cron
}

remove_old_nodes() {
    local old_node_id=$(($NODE_ID-1))
    if [ "$NODE_ID" = "$DEFAULT_LEADER_NODE_ID" ]
    then
        while ! curl "http://$MY_IP:4001/readyz" --no-progress-meter
        do
            echo "my instance is not up yet" | tee -a /home/ec2-user/rqlite_warnings
            sleep 3
        done
        
        while read -r line
        do
            if [ $line -lt $NODE_ID ]
            then
                echo "Attempting to remove $line from the cluster" | tee -a /home/ec2-user/rqlite_warnings
                curl -XDELETE -L --post301 -v "http://$MY_IP:4001/remove" -d "{\"id\": \"$line\"}" | tee -a /home/ec2-user/rqlite-warnings
            fi
        done <<< $(curl --silent "http://$MY_IP:4001/nodes" | jq -r 'keys |.[]') 
    fi
}

main() {
    local script_dir=$(pwd)
    bash shared/wait_boot_finished.sh
    install_rqlite
    cd "$script_dir"
    start_rqlite_cluster
    cd "$script_dir"
    remove_old_nodes
}

main
