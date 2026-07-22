#!/bin/bash
# List current KTP GitHub Sponsors, grouped by tier (highest first).
#
# Requires: gh, authenticated as the sponsored account (afraznein).
# Scope: the sponsor login + tier + amount need NO extra scope beyond a normal
# gh login. Add `read:user` (gh auth refresh -s read:user) only if you also want
# each sponsorship's start date.
set -euo pipefail

gh api graphql -f query='
query {
  viewer {
    sponsorshipsAsMaintainer(first: 100, activeOnly: true) {
      totalCount
      nodes {
        sponsorEntity { __typename ... on User { login } ... on Organization { login } }
        tier { name monthlyPriceInDollars isOneTime }
      }
    }
  }
}' --jq '
  "Active sponsorships: \(.data.viewer.sponsorshipsAsMaintainer.totalCount)",
  (.data.viewer.sponsorshipsAsMaintainer.nodes
    | sort_by(-.tier.monthlyPriceInDollars)[]
    | "  $\(.tier.monthlyPriceInDollars)/mo\(if .tier.isOneTime then " (one-time)" else "" end)  \(.tier.name)  @\(.sponsorEntity.login)")
'
