// Local implementation. Embedded by the version/shape checked 0.66.0 transform.
// This reads an explicit profile-scoped allowlist once. It never learns agents,
// changes creation preferences, or writes configuration or credentials.
function __gs066ReadAllowlist(profileDir, fs = require('node:fs'), path = require('node:path')) {
  const empty = () => new Set();
  if (typeof profileDir !== 'string' || !path.isAbsolute(profileDir)) return empty();
  try {
    const file = path.join(profileDir, 'grok-switch-local-agents.json');
    const stat = fs.lstatSync(file);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 32768) return empty();
    const data = JSON.parse(fs.readFileSync(file, 'utf8'));
    const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
    if (!data || typeof data !== 'object' || Array.isArray(data)
        || data.version !== 1 || data.hostVersion !== '1494ebd'
        || !Array.isArray(data.agentIds) || data.agentIds.length > 32
        || !data.agentIds.every(id => typeof id === 'string' && uuid.test(id))
        || new Set(data.agentIds).size !== data.agentIds.length
        || Object.keys(data).some(key => !['version', 'hostVersion', 'agentIds'].includes(key))) return empty();
    return new Set(data.agentIds);
  } catch { return empty(); }
}
