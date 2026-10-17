// The Windows path rules on Pyodide's file system, which the engine was written for.
const ENOENT = 44;
const PATH_ARGS = {
  lookupPath: [0], analyzePath: [0], open: [0], stat: [0], lstat: [0], mkdir: [0], mkdirTree: [0], mknod: [0],
  create: [0], mkdev: [0], rename: [0, 1], rmdir: [0], unlink: [0], readdir: [0], symlink: [0, 1], readlink: [0],
  chmod: [0], lchmod: [0], chown: [0], lchown: [0], truncate: [0], utime: [0], readFile: [0], writeFile: [0],
  chdir: [0], statfs: [0], findObject: [0],
};

const slashes = p => (typeof p === 'string' && p.startsWith('/') && p.includes('\\') ? p.replace(/\\/g, '/') : p);

export function windowsRules(FS) {
  if (FS.lookupNode.windowsRules) return;
  const exact = FS.lookupNode;
  const lookup = function (parent, name) {
    try {
      return exact.call(FS, parent, name);
    } catch (e) {
      if (!e || e.errno !== ENOENT || name === '.' || name === '..') throw e;
      let names;
      try {
        names = parent.node_ops.readdir(parent);
      } catch (e2) {
        throw e;
      }
      const low = name.toLowerCase();
      const hit = names.find(n => n !== name && n.toLowerCase() === low);
      if (hit === undefined) throw e;
      return exact.call(FS, parent, hit);
    }
  };
  lookup.windowsRules = true;
  FS.lookupNode = lookup;
  for (const [name, idx] of Object.entries(PATH_ARGS)) {
    const fn = FS[name];
    if (typeof fn !== 'function') continue;
    FS[name] = function (...args) {
      for (const i of idx) args[i] = slashes(args[i]);
      return fn.apply(FS, args);
    };
  }
}
