#!/bin/sh
# nginx resolves the backend name itself at request time; give it the container's DNS server.
set -eu
mkdir -p /etc/nginx/snippets
ns=$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf)
echo "resolver ${ns:-127.0.0.11} valid=10s ipv6=off;" > /etc/nginx/snippets/resolver.conf
