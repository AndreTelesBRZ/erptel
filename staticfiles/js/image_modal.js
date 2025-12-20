function openImageModal(src){
  let modal = document.getElementById('image-modal');
  if(!modal){
    modal = document.createElement('div');
    modal.id = 'image-modal';
    modal.className = 'image-modal';
    modal.innerHTML = `
      <div class="image-modal-backdrop" onclick="closeImageModal()"></div>
      <div class="image-modal-content">
        <button class="image-modal-close" onclick="closeImageModal()">×</button>
        <img id="image-modal-img" src="" alt="">
      </div>
    `;
    document.body.appendChild(modal);
  }
  const img = document.getElementById('image-modal-img');
  img.src = src;
  modal.style.display = 'block';
}
function closeImageModal(){
  const modal = document.getElementById('image-modal');
  if(modal) modal.style.display = 'none';
}
