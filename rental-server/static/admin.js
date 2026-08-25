async function adminServiceAction(id, action, danger = false) {
  if (danger && !confirm('このサービスの利用を終了しますか？')) return;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
  try {
    const response = await fetch(`/api/admin/services/${id}/${action}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrf,
      },
    });
    const data = await response.json().catch(() => ({ error: 'invalid response' }));
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    location.reload();
  } catch (error) {
    alert(error.message);
  }
}

window.adminServiceAction = adminServiceAction;
