### Changed

- deploy/k3s-single: `cert.yaml` and the example `hub-values.yaml` carry the join host (`ingress.joinHost`), and the install walkthrough names its DNS record; production serves `join.maity.team` through the chart instead of hand-made Ingresses.