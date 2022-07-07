#!/usr/bin/env bash

apt-get update
apt-get install -y ruby python3 binutils
python3 --version

gem install --no-document fpm -v 1.14.1

gem cleanup
apt-get clean