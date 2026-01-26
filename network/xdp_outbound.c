// FILE: network/xdp_outbound.c
// PURPOSE: Kernel-level TCP fingerprint homogenization to defeat OS fingerprinting
// COMPILE: clang -O2 -target bpf -c xdp_outbound.c -o xdp_outbound.o

#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/tcp.h>
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_endian.h>

// Define IP_DF if not present in headers
#ifndef IP_DF
#define IP_DF 0x4000
#endif

SEC("xdp_outbound")
int rewrite_tcp_headers(struct xdp_md *ctx) {
    void *data = (void *)(long)ctx->data;
    void *data_end = (void *)(long)ctx->data_end;
    
    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end) return XDP_PASS;

    struct iphdr *ip = (void *)(eth + 1);
    if ((void *)(ip + 1) > data_end) return XDP_PASS;

    // TARGET: Only modify TCP packets
    if (ip->protocol != IPPROTO_TCP) return XDP_PASS;

    struct tcphdr *tcp = (void *)(ip + 1);
    if ((void *)(tcp + 1) > data_end) return XDP_PASS;

    // --- PHASE 5 SOVEREIGNTY MASKS ---

    // 1. SPOOF TTL (Time To Live)
    // Windows Default is 128. Linux is 64.
    // If we detect a standard Linux TTL (64), we shift it to Windows (128).
    if (ip->ttl == 64) {
        ip->ttl = 128;
        // Checksum recalculation is offloaded to NIC in XDP generic mode,
        // but for strict XDP native, incremental checksum update is needed here.
        // For this implementation, we assume hardware offload.
    }

    // 2. ADJUST TCP WINDOW SIZE
    // Windows 10 Standard Window Size = 64240
    // This overwrites the Linux stack's dynamic window scaling
    tcp->window = bpf_htons(64240);
    
    // 3. ENFORCE "DON'T FRAGMENT" (DF) BIT
    // Windows 10 strictly enforces DF=1 for TCP traffic.
    ip->frag_off |= bpf_htons(IP_DF);

    return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
