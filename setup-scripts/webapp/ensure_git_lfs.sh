install_git_lfs() {
    # At the time of writing, 2022-12-21, git-lfs packagerepo does not support Amazon Linux 2022,
    # which is generally available but not the default option. We need Amazon Linux 2022
    # for node 18 support for our front-end web, which is the only thing using git-lfs at
    # this time. That is why we install from binaries ourself, skipping yum.

    local arch=$(uname -m)
    # alias aarch64 to arm64, the old name, to match git-lfs naming convention
    if [ "$arch" = "aarch64" ]
    then
        arch="arm64"
    fi

    if ! command -v jq &> /dev/null
    then
        yum install -y jq
    fi

    cd /usr/local/src
    mkdir -p git-lfs
    cd git-lfs
    rm -f release-info.json
    curl -L -s --retry 5 --retry-connrefused -o release-info.json https://api.github.com/repos/git-lfs/git-lfs/releases/latest
    local latest_release_url=$(cat release-info.json | jq -r ".assets[] | .browser_download_url" | grep -Eo "^.*linux-$arch-.*.tar.gz" | head -1)
    local latest_release_version=$(cat release-info.json | jq -r ".tag_name" | grep -Eo "[0-9]+\.[0-9]+\.[0-9]+")
    local fname=$(basename $latest_release_url)
    local install_dir="/usr/local"
    local install_bin="$install_dir/bin"

    curl -L -O -s --retry 5 --retry-connrefused $latest_release_url
    tar -xzf $fname
    rm -f $install_bin/git-lfs
    cp "git-lfs-$latest_release_version/git-lfs" $install_bin
    chmod +x $install_bin/git-lfs
    if git lfs install
    then
        echo "Installed git-lfs $latest_release_version"
    else
        echo "Failed to install git-lfs $latest_release_version"
        exit 1
    fi
}

install_git_lfs_if_necessary() {
    if ! command -v git-lfs &> /dev/null
    then
        local OLD_CWD=$(pwd)
        install_git_lfs
        cd $OLD_CWD
    fi
}

install_git_lfs_if_necessary
