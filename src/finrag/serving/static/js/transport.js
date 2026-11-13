export async function request(url, options) {
  const r = await fetch(url, options);
  let data;
  try {
    data = await r.json();
  } catch {
    throw new Error(`HTTP ${r.status}`);
  }
  if (!r.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${r.status}`);
  return data;
}
export async function streamQuery(input, generate, receive) {
  const response = await fetch(`/query/stream?generate=${generate}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(input)
  });
  if (!response.ok) {
    let b = {};
    try {
      b = await response.json();
    } catch {}
    throw new Error(typeof b.detail === 'string' ? b.detail : `HTTP ${response.status}`);
  }
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = '',
    terminal = false;
  try {
    while (true) {
      const {
        value,
        done
      } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {
        stream: !done
      });
      buffer = buffer.replace(/\r\n/g, '\n');
      let pos;
      while ((pos = buffer.indexOf('\n\n')) >= 0) {
        const block = buffer.slice(0, pos);
        buffer = buffer.slice(pos + 2);
        let kind = 'message';
        const data = [];
        block.split('\n').forEach(line => {
          if (line.startsWith('event:')) kind = line.slice(6).trim();
          if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
        });
        if (data.length) {
          receive(kind, JSON.parse(data.join('\n')));
          if (['result', 'failure'].includes(kind)) terminal = true;
        }
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
  if (!terminal) throw new Error('连接已断开；服务端会请求取消。在途调用可能仍在结算，请刷新历史，勿重复提交。');
}
