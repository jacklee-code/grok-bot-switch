'use strict';
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const executable = process.platform === 'win32' ? 'python' : 'python3';
const result = spawnSync(executable, ['-m', 'unittest', 'discover', '-s', 'experimental/client-066', '-p', 'test_*.py'], {
  cwd: path.join(__dirname, '..'), stdio: 'inherit', windowsHide: true
});
if (result.error) process.stderr.write('Python 3.10+ is required for client archive tests: ' + result.error.message + '\n');
process.exitCode = result.status === null ? 1 : result.status;
