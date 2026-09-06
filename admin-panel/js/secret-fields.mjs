// Server-owned metadata only. Never derive a preview from typed credentials.
export function isSecret(value) {
  return value?.type === 'secret';
}

export function secretLabel(meta) {
  if (!meta?.has_value) return '未配置';
  return typeof meta.last4 === 'string' && meta.last4.length === 4
    ? `已配置 · 尾号 ${meta.last4}` : '已配置';
}

export function providerLabel(provider) {
  return secretLabel({ has_value: provider?.has_credential, last4: provider?.api_key_last4 });
}

// Per-input serial writes protect DB order as well as late response rendering.
export function secretWriter(input, { write, refresh, update }) {
  let revision = 0;
  let queue = Promise.resolve();
  let submitted = '';
  const changed = () => { revision++; };
  const submit = (clear = false) => {
    const value = input.value;
    if (!clear && (!value.trim() || value === submitted)) return queue;
    const stamp = revision;
    submitted = clear ? '' : value;
    queue = queue.catch(() => {}).then(async () => {
      try {
        await write(clear ? { clear: true } : { value });
        const meta = await refresh();
        if (input.isConnected === false) return;
        update(meta);
        if (revision === stamp) input.value = '';
      } finally {
        if (submitted === value || clear) submitted = '';
      }
    });
    return queue;
  };
  return { changed, submit };
}
