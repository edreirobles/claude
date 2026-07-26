const REDACTED = "[REDACTED]";

const patterns: Array<[RegExp, string]> = [
  [/(authorization\s*[:=]\s*(?:bearer|basic)\s+)[^\s,;]+/gi, `$1${REDACTED}`],
  [/((?:set-)?cookie\s*[:=]\s*)[^\r\n]+/gi, `$1${REDACTED}`],
  [
    /(\b(?:[a-z0-9]+[_-])*(?:access[_-]?token|refresh[_-]?token|auth[_-]?token|api[_-]?key|client[_-]?secret|secret[_-]?key|bot[_-]?token|li_at|jsessionid|ct0|password|database_url)\b\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}&]+)/gi,
    `$1${REDACTED}`
  ],
  [/\b\d{7,12}:[A-Za-z0-9_-]{20,}\b/g, REDACTED],
  [/([a-z][a-z0-9+.-]*:\/\/[^\s/@:]+:)[^\s/@]+(@)/gi, `$1${REDACTED}$2`]
];

export function redact(value: unknown): string {
  let output =
    value instanceof Error
      ? `${value.name}: ${value.message}`
      : typeof value === "string"
        ? value
        : JSON.stringify(value) ?? String(value);
  for (const [pattern, replacement] of patterns) {
    output = output.replace(pattern, replacement);
  }
  return output.slice(0, 4000);
}
