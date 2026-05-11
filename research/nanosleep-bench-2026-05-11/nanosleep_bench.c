/*
 * nanosleep_bench.c — measure actual clock_nanosleep granularity on Linux
 *
 * Phase 3a diagnostic for KTP's custom-kernel research. Determines whether
 * `clock_nanosleep(TIMER_ABSTIME)` honors sub-millisecond requests or rounds
 * up to the next CONFIG_HZ tick. The runbook's pre-Stage C hypothesis is
 * that 1ms rounding is the absgrid floor; this measures it directly.
 *
 * Compile:  gcc -O2 -o nanosleep_bench nanosleep_bench.c
 * Run:      ./nanosleep_bench [--rt] [--cpu N]
 *           --rt    request SCHED_FIFO 50 (matches game-server / absgrid setup)
 *           --cpu N pin to CPU N (recommend an isolated core)
 *
 * Output: TSV — req_us, min_us, p50_us, p90_us, p99_us, max_us, mean_us, n
 *
 * No external deps. Self-contained. Safe to run as root or with CAP_SYS_NICE.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/resource.h>

#define ITERATIONS 10000

static int cmp_u64(const void *a, const void *b) {
    uint64_t x = *(const uint64_t*)a, y = *(const uint64_t*)b;
    return (x > y) - (x < y);
}

static uint64_t pct(uint64_t *sorted, int n, double p) {
    int idx = (int)(n * p);
    if (idx >= n) idx = n - 1;
    return sorted[idx];
}

static void bench_at(uint64_t req_ns) {
    uint64_t *deltas = malloc(ITERATIONS * sizeof(uint64_t));
    if (!deltas) { perror("malloc"); exit(1); }

    /* Warm-up — first call often has high jitter from cache misses */
    for (int w = 0; w < 100; w++) {
        struct timespec t;
        clock_gettime(CLOCK_MONOTONIC, &t);
        t.tv_nsec += req_ns;
        if (t.tv_nsec >= 1000000000) { t.tv_sec++; t.tv_nsec -= 1000000000; }
        clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &t, NULL);
    }

    for (int i = 0; i < ITERATIONS; i++) {
        struct timespec t0, t1, target;
        clock_gettime(CLOCK_MONOTONIC, &t0);

        target.tv_sec = t0.tv_sec;
        target.tv_nsec = t0.tv_nsec + req_ns;
        if (target.tv_nsec >= 1000000000) { target.tv_sec++; target.tv_nsec -= 1000000000; }

        int rc = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &target, NULL);
        clock_gettime(CLOCK_MONOTONIC, &t1);

        if (rc != 0) {
            fprintf(stderr, "clock_nanosleep failed: %s\n", strerror(rc));
            exit(1);
        }

        uint64_t elapsed_ns = (uint64_t)(t1.tv_sec - t0.tv_sec) * 1000000000ULL
                            + (uint64_t)t1.tv_nsec - (uint64_t)t0.tv_nsec;
        deltas[i] = elapsed_ns;
    }

    qsort(deltas, ITERATIONS, sizeof(uint64_t), cmp_u64);

    uint64_t min = deltas[0];
    uint64_t max = deltas[ITERATIONS - 1];
    uint64_t p50 = pct(deltas, ITERATIONS, 0.50);
    uint64_t p90 = pct(deltas, ITERATIONS, 0.90);
    uint64_t p99 = pct(deltas, ITERATIONS, 0.99);
    uint64_t sum = 0;
    for (int i = 0; i < ITERATIONS; i++) sum += deltas[i];
    uint64_t mean = sum / ITERATIONS;

    /* Output as microseconds for readability */
    printf("%6lu\t%6lu\t%6lu\t%6lu\t%6lu\t%6lu\t%6lu\t%d\n",
        req_ns / 1000, min / 1000, p50 / 1000, p90 / 1000, p99 / 1000,
        max / 1000, mean / 1000, ITERATIONS);
    fflush(stdout);
    free(deltas);
}

int main(int argc, char **argv) {
    int use_rt = 0;
    int cpu = -1;

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "--rt") == 0) use_rt = 1;
        else if (strcmp(argv[i], "--cpu") == 0 && i + 1 < argc) cpu = atoi(argv[++i]);
    }

    /* Lock pages — prevent swap-in delays during measurement */
    if (mlockall(MCL_CURRENT | MCL_FUTURE) != 0)
        fprintf(stderr, "mlockall failed (continuing): %s\n", strerror(errno));

    if (cpu >= 0) {
        cpu_set_t set;
        CPU_ZERO(&set);
        CPU_SET(cpu, &set);
        if (sched_setaffinity(0, sizeof(set), &set) != 0) {
            fprintf(stderr, "sched_setaffinity to CPU %d failed: %s\n", cpu, strerror(errno));
            return 1;
        }
        fprintf(stderr, "# pinned to CPU %d\n", cpu);
    }

    if (use_rt) {
        struct sched_param p = { .sched_priority = 50 };
        if (sched_setscheduler(0, SCHED_FIFO, &p) != 0) {
            fprintf(stderr, "sched_setscheduler SCHED_FIFO 50 failed: %s\n", strerror(errno));
            return 1;
        }
        fprintf(stderr, "# SCHED_FIFO priority 50\n");
    }

    fprintf(stderr, "# kernel: ");
    fflush(stderr);
    system("uname -r >&2");

    /* Header */
    printf("# req_us\tmin_us\tp50_us\tp90_us\tp99_us\tmax_us\tmean_us\tn\n");

    /* Sweep request intervals — span sub-tick (CONFIG_HZ=1000 → 1ms tick) */
    uint64_t reqs_us[] = { 100, 200, 500, 800, 900, 999, 1000, 1100, 1500, 2000, 5000 };
    int n_reqs = sizeof(reqs_us) / sizeof(reqs_us[0]);

    for (int i = 0; i < n_reqs; i++) {
        bench_at(reqs_us[i] * 1000);
    }
    return 0;
}
