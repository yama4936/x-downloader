const form = document.querySelector('#form');
const button = document.querySelector('#submit');
const status = document.querySelector('#status');
const results = document.querySelector('#results');
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  button.disabled = true;
  button.textContent = '取得中…';
  status.className = '';
  status.textContent = '動画を探しています。しばらくお待ちください。';
  results.replaceChildren();
  try {
    const response = await fetch('/api/analyze', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: document.querySelector('#url').value.trim()})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'URLを確認してください。');
    for (const video of data.videos) {
      const block = document.createElement('section'); block.className = 'video';
      const title = document.createElement('h2'); title.textContent = video.title;
      const choices = document.createElement('div'); choices.className = 'choices';
      for (const quality of video.qualities) {
        const link = document.createElement('a');
        link.className = 'download'; link.href = quality.download;
        link.textContent = `${quality.label} を保存 ↓`;
        choices.append(link);
      }
      block.append(title, choices); results.append(block);
    }
    status.textContent = '動画が見つかりました。画質を選んで保存してください（リンクは10分間有効）。';
  } catch (error) {
    status.className = 'error';
    status.textContent = error instanceof TypeError ? '通信に失敗しました。接続を確認してお試しください。' : error.message;
  } finally {
    button.disabled = false; button.textContent = '動画を取得 ↗';
  }
});
