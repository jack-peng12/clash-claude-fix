function main(config) {

  config = config || {};

  config.tun = {
    enable: true,
    stack: "mixed",
    "dns-hijack": ["any:53"],
    "auto-route": true,
    "auto-detect-interface": true,
    "strict-route": true
  };

  config.dns = {
    enable: true,
    ipv6: false,
    "default-nameserver": ["223.5.5.5", "119.29.29.29"],
    "enhanced-mode": "fake-ip",
    "fake-ip-range": "198.18.0.1/16",
    "fake-ip-filter": [
      "*.lan", "*.local",
      "stun.*",
      "+.stun.l.google.com",
      "+.stun.services.mozilla.com"
    ],
    nameserver: [
      "https://doh.pub/dns-query",
      "https://dns.alidns.com/dns-query"
    ],
    fallback: [
      "https://1.1.1.1/dns-query",
      "https://8.8.8.8/dns-query"
    ]
  };

  const groups = config["proxy-groups"] || [];
  let proxyGroup = "PROXY";

  const keywords = ["选择", "select", "节点", "proxy", "默认", "手动"];

  for (const g of groups) {
    const name = (g.name || "").toLowerCase();
    if (keywords.some(k => name.includes(k))) {
      proxyGroup = g.name;
      break;
    }
  }

  if (groups.length > 0 && proxyGroup === "PROXY") {
    proxyGroup = groups[0].name;
  }

  const rules = [
    `DOMAIN-SUFFIX,anthropic.com,${proxyGroup}`,
    `DOMAIN-SUFFIX,claude.ai,${proxyGroup}`,
    `DOMAIN-SUFFIX,claudeusercontent.com,${proxyGroup}`,
    `DOMAIN-KEYWORD,anthropic,${proxyGroup}`,
    `DOMAIN-SUFFIX,oaistatic.com,${proxyGroup}`,
    `DOMAIN-SUFFIX,oaiusercontent.com,${proxyGroup}`
  ];

  config.rules = [...rules, ...(config.rules || [])];

  return config;
}