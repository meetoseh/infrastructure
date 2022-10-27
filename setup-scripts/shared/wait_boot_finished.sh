wait_internet() {
    while ! curl google.com >> /dev/null
    do
        sleep 5
    done
}

install_basic_dependencies() {
    yum update -y
    echo "exclude=python3" >> /etc/yum.conf

    if amazon-linux-extras --help >> /dev/null 2&>1
    then
        # amazon linux 2022 has no epel-release yet?
        amazon-linux-extras enable epel=stable
        yum clean metadata
        rpm --rebuilddb
        yum install -y epel-release git jq screen wget
        yum update -y
    else
        yum install -y git jq screen wget
    fi
}

install_latest_python() {
    if ! amazon-linux-extras --help >> /dev/null 2&>1
    then
        # amazon linux 2022 comes with python?
        return
    fi
    local latest_version=$(amazon-linux-extras | grep -oE "python3\.[0-9]+" | grep -oE "3\.[0-9]+" | sort -t '.' -k1,1nr -k2,2nr | head -n 1)
    amazon-linux-extras enable python$latest_version | tail -n 2 | cut -c 4- | sed 's/yum install/yum -y install/g' > python_install.sh
    rpm --rebuilddb
    bash python_install.sh
    rm python_install.sh

    rm /usr/bin/python3
    ln -s /usr/bin/python$latest_version /usr/bin/python3

    python3 -m pip install -U pip
}

verify_iam_profile() {
    curl http://169.254.169.254/latest/meta-data/iam/info | jq -e .InstanceProfileId
    return $?
}

wait_iam_profile() {
    local ctr="0"
    while ! verify_iam_profile
    do
        ctr=$(($ctr + 1))
        echo "initialization failed to verify iam profile (ctr=$ctr)" >> /home/ec2-user/boot_warnings
        sleep 30

        if (($ctr > 5))
        then
            echo "iam profile never arrived, giving up on it" >> /home/ec2-user/boot_warnings
            break
        fi
    done
}

wait_internet
install_basic_dependencies
wait_iam_profile
install_latest_python
