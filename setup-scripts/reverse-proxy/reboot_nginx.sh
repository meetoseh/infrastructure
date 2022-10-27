#!/usr/bin/env bash
if ! nginx -s quit
then
    echo "Failed to quit nginx, attempting to kill by process name"
    while [ -n "$(pgrep nginx)" ]
    do
        echo "Killing $(pgrep nginx | head -n 1)"
        kill $(pgrep nginx | head -n 1)
        sleep 1
    done
fi

while [ -n "$(pgrep nginx)" ]
do
    echo "Waiting for nginx to shut off"
    sleep 1
done

echo "Rebooting nginx"
nginx
