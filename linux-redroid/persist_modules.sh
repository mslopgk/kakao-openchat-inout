#!/bin/bash
# 커스텀 커널은 모듈 자동 로드가 docker 기동보다 늦어 실패 → 부팅 시 미리 로드
cat > /etc/modules-load.d/docker-redroid.conf <<'EOF'
nf_tables
nft_chain_nat
nft_compat
nf_nat
xt_MASQUERADE
xt_addrtype
xt_conntrack
br_netfilter
bridge
veth
overlay
iptable_nat
iptable_filter
xt_nat
xt_tcpudp
xt_multiport
xt_mark
nf_conntrack
ip_tables
nft_nat
nft_masq
EOF
cat /etc/modules-load.d/docker-redroid.conf | wc -l
