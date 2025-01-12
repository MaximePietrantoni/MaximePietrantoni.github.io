(function () {
  var messageCenter = document.getElementById("messageCenter");
  function sendMessage(html) {
    var elem = document.createElement("div");
    elem.className = "message";
    elem.innerHTML = html;
    messageCenter.prepend(elem);
    setTimeout(function () { messageCenter.removeChild(elem); }, 4300);
    setTimeout(function () { elem.classList.add('deleted'); }, 4000);
    return elem;
  }

  function copyToClipboard(str) {
    var el = document.createElement('textarea');
    el.value = str;
    el.setAttribute('readonly', '');
    el.style.position = 'absolute';
    el.style.left = '-9999px';
    document.body.appendChild(el);
    var selected = (document.getSelection().rangeCount > 0) ? document.getSelection().getRangeAt(0) : false;
    el.select();
    document.execCommand('copy');
    document.body.removeChild(el);
    if (selected) {
      document.getSelection().removeAllRanges();
      document.getSelection().addRange(selected);
    }
  };

  var bibElements = document.querySelectorAll("a[data-bib]:not([data-bib=''])");
  function bibClickClosure(elem) {
    elem.addEventListener('click', function () {
        var bib = decodeURIComponent(elem.getAttribute('data-bib'));
        copyToClipboard(bib);
        sendMessage('<i class="fa fa-check"></i> copied!');
    });
  }
  for(var i = 0; i < bibElements.length; ++i) {
    var elem = bibElements[i];
    bibClickClosure(elem);
  }
})();
