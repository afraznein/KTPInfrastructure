### Changed
- A withheld capture stream now says why its counters do not reconcile: lines that never reached the daemon, a producer drop, or a daemon rejection with its correlation failures. The old reason named the stream and stopped, so a report could not tell transport loss from a rejected frag.
