document.getElementById('sidebar-toggle')?.addEventListener('click', () => document.getElementById('sidebar')?.classList.toggle('open'));
document.querySelectorAll('[data-confirm]').forEach(el => el.addEventListener('click', event => { if (!confirm(el.dataset.confirm)) event.preventDefault(); }));
const dropzone = document.querySelector('[data-dropzone]');
if (dropzone) {
  const input = document.getElementById('source-file');
  dropzone.addEventListener('click', () => input.click());
  ['dragenter','dragover'].forEach(type => dropzone.addEventListener(type, e => {e.preventDefault(); dropzone.classList.add('dragover');}));
  ['dragleave','drop'].forEach(type => dropzone.addEventListener(type, e => {e.preventDefault(); dropzone.classList.remove('dragover');}));
  dropzone.addEventListener('drop', e => { if(e.dataTransfer.files.length) {input.files=e.dataTransfer.files; input.dispatchEvent(new Event('change'));} });
  input.addEventListener('change', () => { const name=document.getElementById('selected-file'); if(name) name.textContent=input.files[0]?.name || 'No file selected'; });
}
