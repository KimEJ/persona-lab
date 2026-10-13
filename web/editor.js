'use strict';
(function(global){
 const escape=text=>String(text).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function inline(text){
  const protectedHTML=[];
  const protect=html=>{protectedHTML.push(html);return '\uE000'+(protectedHTML.length-1)+'\uE001';};
  let value=escape(text).replace(/`([^`]+)`/g,(_,code)=>protect('<code>'+code+'</code>'));
  value=value.replace(/\[([^\]]+)\]\(([^\s)]+)\)/g,(whole,label,url)=>/^https?:\/\//i.test(url)?protect('<a href="'+url+'" rel="noreferrer noopener">'+label.replace(/\uE000(\d+)\uE001/g,(_,index)=>protectedHTML[index])+'</a>'):whole);
  value=value.replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/__([^_]+)__/g,'<strong>$1</strong>').replace(/\*([^*\n]+)\*/g,'<em>$1</em>').replace(/_([^_\n]+)_/g,'<em>$1</em>');
  return value.replace(/\uE000(\d+)\uE001/g,(whole,index)=>protectedHTML[index]||whole);
 }
 // Adapted from MarkText/Muya utils, commit 0d8dba02. MIT; see assets/licenses/MarkText-LICENSE.txt.
 function firstWordOfInfo(info){return info.trimStart().match(/\S*/)?.[0]??'';}
 const FENCE_LINE_REG=/^ {0,3}(`{3,}|~{3,})([^\n]*)/;
 function parseFenceLine(text){const match=FENCE_LINE_REG.exec(text);if(!match)return null;const fence=match[1],info=match[2];if(fence[0]==='`'&&info.includes('`'))return null;return{fenceChar:fence[0],fenceLength:fence.length,info};}
 function renderMarkdown(markdown){
  const pieces=markdown.split(/(\r\n|\r|\n)/),sourceLines=[];let position=0;
  for(let i=0;i<pieces.length;i+=2){sourceLines.push({text:pieces[i],start:position,end:position+pieces[i].length});position+=pieces[i].length+(pieces[i+1]?.length||0);}
  const lines=sourceLines.map(line=>line.text),blocks=[];let paragraph=[],paragraphStart=0,lists=[],listParts=[],listStart=0,listEnd=0,code=null,codeStart=0,codeLines=[];
  const emit=(html,start,end)=>blocks.push({html,start:sourceLines[start].start,end:sourceLines[end].end});
  const flushParagraph=()=>{if(paragraph.length){emit('<p>'+inline(paragraph.join('\n')).replace(/\n/g,'<br>')+'</p>',paragraphStart,paragraphStart+paragraph.length-1);paragraph=[];}};
  const closeList=()=>{const list=lists.pop();listParts.push('</li></'+list.kind+'>');};
  const flushList=()=>{if(!lists.length)return;while(lists.length)closeList();emit(listParts.join(''),listStart,listEnd);listParts=[];};
  const emitCode=end=>emit('<pre data-md-fence="'+code.fenceChar+'" data-md-length="'+code.fenceLength+'" data-md-info="'+escape(code.info)+'"><code>'+escape(codeLines.join('\n'))+'</code></pre>',codeStart,end);
  const cells=line=>line.trim().replace(/^\|/,'').replace(/\|$/,'').split(/(?<!\\)\|/).map(cell=>cell.replace(/\\\|/g,'|').trim());
  for(let lineIndex=0;lineIndex<lines.length;lineIndex++){
   const line=lines[lineIndex];
   const fence=parseFenceLine(line);
   if(code!==null){const closing=line.match(/^ {0,3}(`{3,}|~{3,})[ \t]*$/);if(closing&&closing[1][0]===code.fenceChar&&closing[1].length>=code.fenceLength){emitCode(lineIndex);code=null;codeLines=[];}else codeLines.push(line);continue;}
   if(fence){flushParagraph();flushList();code=fence;codeStart=lineIndex;continue;}
   if(line.includes('|')&&lineIndex+1<lines.length&&cells(lines[lineIndex+1]).every(cell=>/^:?-{3,}:?$/.test(cell))){
    flushParagraph();flushList();const headings=cells(line),start=lineIndex;const alignments=cells(lines[lineIndex+1]).map(cell=>cell.startsWith(':')&&cell.endsWith(':')?'center':cell.endsWith(':')?'right':cell.startsWith(':')?'left':'');lineIndex++;
    const rows=[];while(lineIndex+1<lines.length&&lines[lineIndex+1].includes('|')&&lines[lineIndex+1].trim())rows.push(cells(lines[++lineIndex]));
    const cellHTML=(tag,cell,index)=>'<'+tag+(alignments[index]?' class="md-'+alignments[index]+'"':'')+'>'+inline(cell)+'</'+tag+'>';
    emit('<table data-md-align="'+alignments.join(',')+'"><thead><tr>'+headings.map((cell,index)=>cellHTML('th',cell,index)).join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+headings.map((_,index)=>cellHTML('td',row[index]||'',index)).join('')+'</tr>').join('')+'</tbody></table>',start,lineIndex);continue;
   }
   if(!line.trim()){flushParagraph();flushList();continue;}
   const heading=line.match(/^(#{1,6})\s+(.+?)\s*#*\s*$/);
   if(heading){flushParagraph();flushList();const level=heading[1].length;emit('<h'+level+'>'+inline(heading[2])+'</h'+level+'>',lineIndex,lineIndex);continue;}
   const bullet=line.match(/^(\s*)[-*+]\s+(.+)$/);const ordered=line.match(/^(\s*)(\d+)\.\s+(.+)$/);
   if(bullet||ordered){flushParagraph();const kind=bullet?'ul':'ol',indent=(bullet||ordered)[1].replace(/\t/g,'    ').length;
    if(lists.length===1&&lists[0].indent===indent&&lists[0].kind!==kind)flushList();
    if(!lists.length)listStart=lineIndex;
    listEnd=lineIndex;
    while(lists.length&&lists.at(-1).indent>indent)closeList();
    if(lists.length&&lists.at(-1).indent===indent&&lists.at(-1).kind!==kind)closeList();
    if(lists.length&&lists.at(-1).indent===indent)listParts.push('</li>');
    else{listParts.push('<'+kind+(ordered?' start="'+Number(ordered[2])+'"':'')+'>');lists.push({kind,indent});}
    listParts.push('<li>'+inline(bullet?bullet[2]:ordered[3]));continue;
   }
   flushList();
   if(/^>\s?/.test(line)){flushParagraph();emit('<blockquote><p>'+inline(line.replace(/^>\s?/,''))+'</p></blockquote>',lineIndex,lineIndex);continue;}
   if(/^\s*(?:---+|\*\*\*+)\s*$/.test(line)){flushParagraph();emit('<hr>',lineIndex,lineIndex);continue;}
   if(!paragraph.length)paragraphStart=lineIndex;
   paragraph.push(line);
  }
  if(code!==null)emitCode(lines.length-1);
  flushParagraph();flushList();return blocks;
 }
 function toHTML(markdown){return renderMarkdown(markdown).map(block=>block.html).join('')||'<p><br></p>';}
 function toMarkdown(element){
  const codeBlocks=[];
  const walk=node=>{
   if(node.nodeType===3)return node.nodeValue.replace(/\u00a0/g,' ');
   if(node.nodeType!==1)return '';
   const tag=node.tagName.toLowerCase();const inside=()=>Array.from(node.childNodes).map(walk).join('');
   if(['script','style','iframe','object'].includes(tag))return '';
   if(tag==='br')return '\n';
   if(tag==='strong'||tag==='b')return '**'+inside()+'**';
   if(tag==='em'||tag==='i')return '*'+inside()+'*';
   if(tag==='a')return /^https?:\/\//i.test(node.getAttribute('href')||'')?'['+inside()+']('+node.getAttribute('href')+')':inside();
   if(tag==='code'&&node.parentElement?.tagName!=='PRE')return '`'+inside()+'`';
   if(tag==='pre'){const char=node.dataset.mdFence||'`';let length=Number(node.dataset.mdLength)||3;const runs=Array.from(node.textContent.matchAll(char==='`'?/^ {0,3}(`+)[ \t]*$/gm:/^ {0,3}(~+)[ \t]*$/gm),match=>match[1]);length=Math.max(length,...runs.map(run=>run.length+1));const fence=char.repeat(length);codeBlocks.push(fence+(node.dataset.mdInfo||'')+'\n'+node.textContent+'\n'+fence);return '\n\n\uE000CODE'+(codeBlocks.length-1)+'\uE001\n\n';}
   if(tag==='table'){
    const rows=Array.from(node.querySelectorAll('tr')).map(row=>Array.from(row.children).map(cell=>Array.from(cell.childNodes).map(walk).join('').trim().replace(/\|/g,'\\|').replace(/\n+/g,' ')));
    if(!rows.length)return '';const align=(node.dataset.mdAlign||'').split(',');const format=row=>'| '+row.join(' | ')+' |';return '\n\n'+format(rows[0])+'\n'+format(rows[0].map((_,i)=>align[i]==='center'?':---:':align[i]==='right'?'---:':align[i]==='left'?':---':'---'))+'\n'+rows.slice(1).map(format).join('\n')+'\n\n';
   }
   if(/^h[1-6]$/.test(tag))return '\n\n'+'#'.repeat(Number(tag[1]))+' '+inside().trim()+'\n\n';
   if(tag==='p'||tag==='div')return '\n\n'+inside()+'\n\n';
   if(tag==='blockquote')return '\n\n'+inside().trim().split('\n').map(line=>'> '+line).join('\n')+'\n\n';
   if(tag==='ul'||tag==='ol')return '\n\n'+Array.from(node.children).filter(n=>n.tagName==='LI').map((li,index)=>{const prefix=tag==='ol'?((Number(node.getAttribute('start'))||1)+index)+'. ':'- ';let body='';for(const child of li.childNodes){if(child.nodeType===1&&['UL','OL'].includes(child.tagName))body+='\n'+walk(child).trim().split('\n').map(line=>' '.repeat(prefix.length)+line).join('\n');else body+=walk(child);}return prefix+body.trim();}).join('\n')+'\n\n';
   if(tag==='hr')return '\n\n---\n\n';
   return inside();
  };
  return Array.from(element.childNodes).map(walk).join('').replace(/\n{3,}/g,'\n\n').trim().replace(/\uE000CODE(\d+)\uE001/g,(_,index)=>codeBlocks[index]);
 }
 function setCaret(element,offset){
  const walker=document.createTreeWalker(element,NodeFilter.SHOW_TEXT);let node;
  while((node=walker.nextNode())){if(offset<=node.length){const range=document.createRange();range.setStart(node,offset);range.collapse(true);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);return;}offset-=node.length;}
  const range=document.createRange();range.selectNodeContents(element);range.collapse(offset===0);const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);
 }
 class Editor{
  constructor(element,onChange){this.element=element;this.onChange=onChange;this.original='';this.lastEmitted='';this.sources=new Map();this.sourceCounter=0;this.groupCounter=0;this.dirty=false;this.transforming=false;this.composing=false;this.savedRange=null;this.history=[];this.future=[];this.lastOperation=null;this.lastSelection={anchor:0,focus:0};
   element.addEventListener('compositionstart',()=>this.composing=true);
   element.addEventListener('compositionend',()=>{this.composing=false;this.changed({});});
   element.addEventListener('input',event=>this.changed(event));
   element.addEventListener('beforeinput',event=>{this.beforeSelection=this.selectionOffsets();if(event.inputType==='historyUndo'||event.inputType==='historyRedo'){event.preventDefault();this[event.inputType==='historyUndo'?'undo':'redo']();return;}this.shortcut(event);});
   element.addEventListener('paste',event=>{if(element.contentEditable!=='true')return;event.preventDefault();const text=event.clipboardData.getData('text/plain'),selection=window.getSelection();if([...text].length>20000){this.onChange(null,'문서는 20,000자까지 사용할 수 있습니다.');return;}const html=element.innerHTML,dirty=this.dirty;this.beforeSelection=this.selectionOffsets();const whole=!element.textContent.trim()||selection.toString().replace(/\s/g,'')===element.textContent.replace(/\s/g,'');if(whole){element.innerHTML=this.sourceHTML(text);setCaret(element,Infinity);}else document.execCommand('insertHTML',false,this.sourceHTML(text));this.dirty=true;if([...this.getMarkdown()].length>20000){element.innerHTML=html;this.dirty=dirty;setCaret(element,this.beforeSelection.focus);this.beforeSelection=null;this.onChange(null,'문서는 20,000자까지 사용할 수 있습니다.');return;}this.changed({inputType:'insertFromPaste'});});
   document.addEventListener('selectionchange',()=>this.rememberSelection());
   element.addEventListener('keydown',event=>{if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='z'){event.preventDefault();this[event.shiftKey?'redo':'undo']();}else if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='b'){event.preventDefault();document.execCommand('bold');this.changed({inputType:'formatBold'});}else if((event.metaKey||event.ctrlKey)&&event.key.toLowerCase()==='i'){event.preventDefault();document.execCommand('italic');this.changed({inputType:'formatItalic'});}});
  }
  sourceHTML(markdown){const group=++this.groupCounter;const blocks=renderMarkdown(markdown);let lastEnd=0;return blocks.map((block,order)=>{const box=document.createElement('div');box.innerHTML=block.html;const node=box.firstElementChild;const key=String(++this.sourceCounter);node.dataset.mdSource=key;this.sources.set(key,{group,order,raw:markdown.slice(block.start,block.end),before:markdown.slice(lastEnd,block.start),after:order===blocks.length-1?markdown.slice(block.end):null,html:node.outerHTML});lastEnd=block.end;return node.outerHTML;}).join('')||'<p><br></p>';}
  setMarkdown(markdown,editable=true){this.original=markdown;this.lastEmitted=markdown;this.dirty=false;this.sources.clear();this.savedRange=null;this.element.innerHTML=this.sourceHTML(markdown);this.setEditable(editable);this.history=[];this.future=[];this.lastOperation=null;this.beforeSelection=null;this.lastSelection={anchor:0,focus:0};this.updateEmpty();this.applyHints();}
  replaceMarkdown(markdown){if(this.element.contentEditable!=='true')return false;if([...markdown].length>20000){this.onChange(null,'문서는 20,000자까지 사용할 수 있습니다.');return false;}const previous=this.getMarkdown();if(markdown===previous)return false;this.flush();this.history.push({markdown:previous,selection:this.selectionOffsets()});if(this.history.length>100)this.history.shift();this.future=[];this.composing=false;this.restoreHistory({markdown,selection:{anchor:0,focus:0}});return true;}
  setEditable(editable){this.element.contentEditable=String(editable);this.element.setAttribute('aria-readonly',String(!editable));this.applyHints();}
  captureHistory(){return {markdown:this.getMarkdown(),history:this.history.slice(),future:this.future.slice(),selection:this.selectionOffsets()};}
  restoreEditor(snapshot,editable=true){this.setMarkdown(snapshot.markdown,editable);this.history=snapshot.history.slice();this.future=snapshot.future.slice();this.lastSelection=snapshot.selection;}
  getMarkdown(){if(!this.dirty)return this.original;let result='',previous=null,last=null;for(const node of this.element.childNodes){const source=node.nodeType===1?this.sources.get(node.dataset.mdSource):null;let text;if(source&&source.html===node.outerHTML)text=source.raw;else{const box=document.createElement('div');box.append(node.cloneNode(true));text=toMarkdown(box);}if(!text)continue;const contiguous=source&&previous&&source.group===previous.group&&source.order===previous.order+1;result+=(result?(contiguous?source.before:'\n\n'):(source?.order===0?source.before:''))+text;previous=source;last=source;}return result+(last?.after||'');}
  setHints(hints){this.hints=hints;this.applyHints();}
  applyHints(){if(this.element.contentEditable!=='true'||!this.hints)return;for(const heading of this.element.querySelectorAll(':scope > h2')){const hint=this.hints[heading.textContent];if(!hint)continue;let next=heading.nextElementSibling;if(!next||/^H[1-6]$/.test(next.tagName)){next=document.createElement('p');next.innerHTML='<br>';heading.after(next);}if(next.tagName==='P'&&!next.textContent.trim()){next.dataset.hint=hint;next.dataset.hintEmpty='true';}}}
  notify(event={}){const markdown=this.getMarkdown();if([...markdown].length>20000){this.onChange(null,'문서는 20,000자까지 사용할 수 있습니다.');return;}if(markdown!==this.lastEmitted){const time=Date.now(),block=this.block(),blockKey=block?.nodeType===1?block.dataset.mdSource||block.tagName:'text';const grouped=event.inputType==='insertText'&&this.lastOperation?.type==='insertText'&&this.lastOperation.block===blockKey&&time-this.lastOperation.time<1000;if(!grouped)this.history.push({markdown:this.lastEmitted,selection:this.beforeSelection||this.lastSelection});if(this.history.length>100)this.history.shift();this.future=[];this.lastOperation={type:event.inputType,block:blockKey,time};this.lastEmitted=markdown;this.lastSelection=this.selectionOffsets();this.beforeSelection=null;this.onChange(markdown);}}
  selectionOffsets(){const selection=window.getSelection();const offset=(node,index)=>{if(!node||!this.element.contains(node))return 0;const range=document.createRange();range.selectNodeContents(this.element);range.setEnd(node,index);return range.toString().length;};return{anchor:offset(selection?.anchorNode,selection?.anchorOffset||0),focus:offset(selection?.focusNode,selection?.focusOffset||0)};}
  restoreHistory(entry){this.original=entry.markdown;this.lastEmitted=entry.markdown;this.dirty=false;this.sources.clear();this.savedRange=null;this.beforeSelection=null;this.element.innerHTML=this.sourceHTML(entry.markdown);this.lastOperation=null;this.applyHints();this.element.focus();setCaret(this.element,entry.selection?.focus||0);this.lastSelection=this.selectionOffsets();this.rememberSelection();this.updateEmpty();this.onChange(entry.markdown);}
  undo(){if(this.element.contentEditable!=='true'||!this.history.length)return;this.future.push({markdown:this.getMarkdown(),selection:this.selectionOffsets()});this.restoreHistory(this.history.pop());}
  redo(){if(this.element.contentEditable!=='true'||!this.future.length)return;this.history.push({markdown:this.getMarkdown(),selection:this.selectionOffsets()});this.restoreHistory(this.future.pop());}
  flush(){if(this.dirty)this.notify();}
  rememberSelection(){const selection=window.getSelection();if(selection?.rangeCount&&this.element.contains(selection.anchorNode)&&this.element.contains(selection.focusNode))this.savedRange=selection.getRangeAt(0).cloneRange();}
  restoreSelection(){if(this.element.contentEditable!=='true')return false;const selection=window.getSelection(),saved=this.savedRange?.cloneRange();this.element.focus();if(saved&&this.element.contains(saved.commonAncestorContainer)){selection.removeAllRanges();selection.addRange(saved);return true;}const range=document.createRange();range.selectNodeContents(this.element);range.collapse(false);selection.removeAllRanges();selection.addRange(range);return true;}
  format(tag){if(!this.restoreSelection())return;document.execCommand(tag);this.changed({});}
  formatBlock(tag){if(!this.restoreSelection()||!/^p$|^h[1-6]$/.test(tag))return;const block=this.block();if(!block)return;const offset=block.textContent.length;this.replaceBlock(block,'<'+tag+'>'+(block.nodeType===3?escape(block.textContent):block.innerHTML)+'</'+tag+'>',offset);this.changed({});}
  linkInfo(){this.restoreSelection();const selection=window.getSelection();const parent=selection?.anchorNode?.nodeType===1?selection.anchorNode:selection?.anchorNode?.parentElement;const link=parent?.closest('a');if(link&&this.element.contains(link)){const range=document.createRange();range.selectNode(link);this.savedRange=range;return{text:link.textContent,url:link.getAttribute('href')};}return{text:selection?.toString()||'',url:''};}
  applyLink(text,url){if(!this.restoreSelection())return;try{const parsed=new URL(url);if(!['https:','http:'].includes(parsed.protocol)||!parsed.hostname)throw Error();}catch{throw new Error('http 또는 https 주소를 입력하세요.');}document.execCommand('insertHTML',false,'<a href="'+escape(url)+'" rel="noreferrer noopener">'+escape(text||url)+'</a>');this.changed({});}
  insertTable(){if(!this.restoreSelection())return;document.execCommand('insertHTML',false,'<table><thead><tr><th>항목</th><th>내용</th></tr></thead><tbody><tr><td><br></td><td><br></td></tr></tbody></table>');this.changed({});}
  tableAction(action){if(!this.restoreSelection())return;const selection=window.getSelection();const parent=selection.anchorNode.nodeType===1?selection.anchorNode:selection.anchorNode.parentElement;const cell=parent.closest('td,th'),table=cell?.closest('table');if(!table||!this.element.contains(table))return;const clone=table.cloneNode(true),rowIndex=Array.from(table.rows).indexOf(cell.parentElement),column=cell.cellIndex;
   if(action==='row-add'){const row=document.createElement('tr');for(let i=0;i<table.rows[0].cells.length;i++){const td=document.createElement('td');td.innerHTML='<br>';row.append(td);}const tbody=clone.querySelector('tbody')||clone.appendChild(document.createElement('tbody'));const current=clone.rows[rowIndex];if(current.parentElement===tbody)current.after(row);else tbody.prepend(row);}
   else if(action==='column-add'){for(const row of clone.rows){const td=document.createElement(row.parentElement.tagName==='THEAD'?'th':'td');td.innerHTML='<br>';row.cells[column].after(td);}const align=(clone.dataset.mdAlign||'').split(',');align.splice(column+1,0,'');clone.dataset.mdAlign=align.join(',');}
   else if(action==='row-remove'){if(clone.rows[rowIndex].parentElement.tagName==='THEAD')return;clone.rows[rowIndex].remove();}
   else if(action==='column-remove'){if(clone.rows[0].cells.length===1)return;for(const row of clone.rows)row.cells[column].remove();const align=(clone.dataset.mdAlign||'').split(',');align.splice(column,1);clone.dataset.mdAlign=align.join(',');}
   else return;
   this.replaceBlock(table,clone.outerHTML,0);this.changed({});
  }
  updateEmpty(){this.element.dataset.empty=String(!this.element.textContent.trim());for(const p of this.element.querySelectorAll('[data-hint]'))p.dataset.hintEmpty=String(!p.textContent.trim());}
  block(){const selection=window.getSelection();let node=selection?.anchorNode;if(!node||!this.element.contains(node))return null;let element=node.nodeType===1?node:node.parentElement;if(element===this.element)return node.nodeType===3?node:null;while(element&&element!==this.element){if(['P','DIV','H1','H2','H3','H4','H5','H6','LI'].includes(element.tagName))return element;element=element.parentElement;}return null;}
  replaceBlock(block,html,offset){
   this.transforming=true;const selection=window.getSelection();const range=document.createRange();range.selectNode(block);selection.removeAllRanges();selection.addRange(range);
   const marker='shortcut-'+Date.now();const source=block.nodeType===1?block.dataset.mdSource:null;const marked=html.replace(/^<([a-z0-9]+)/,'<$1 data-md-shortcut="'+marker+'"'+(source&&!html.includes('data-md-source=')?' data-md-source="'+source+'"':''));
   document.execCommand('insertHTML',false,marked);
   const inserted=this.element.querySelector('[data-md-shortcut="'+marker+'"]');
   if(inserted){inserted.removeAttribute('data-md-shortcut');const next=inserted.querySelector('li,p')||inserted;setCaret(next,offset);}
   this.transforming=false;
  }
  shortcut(event){if(this.composing||event.isComposing||this.element.contentEditable!=='true'||event.inputType!=='insertText'||!/^\s$/.test(event.data||''))return;
   const block=this.block();if(!block)return;const text=block.textContent.trim();const heading=text.match(/^(#{1,6})$/);const bullet=/^[-*+]$/.test(text);const ordered=/^\d+\.$/.test(text);const quote=text==='>';
   if(!heading&&!bullet&&!ordered&&!quote)return;
   event.preventDefault();
   if(heading){const tag='h'+heading[1].length;this.replaceBlock(block,'<'+tag+'><br></'+tag+'>',0);}
   else if(quote)this.replaceBlock(block,'<blockquote><p><br></p></blockquote>',0);
   else this.replaceBlock(block,ordered?'<ol><li><br></li></ol>':'<ul><li><br></li></ul>',0);
   this.dirty=true;this.updateEmpty();this.notify({inputType:'format'});
  }
  changed(event){if(this.transforming||this.element.contentEditable!=='true')return;this.dirty=true;this.updateEmpty();if(this.composing||event.isComposing)return;
   if(!this.composing&&!event.isComposing&&!String(event.inputType||'').startsWith('history')){
    const block=this.block();const selection=window.getSelection();
    if(block&&(block.nodeType===3||['P','DIV'].includes(block.tagName))&&/^\s*#{1,6}\s/.test(block.textContent)){
     const match=block.textContent.match(/^\s*(#{1,6})\s+([\s\S]*)$/);const content=match[2];const tag='h'+match[1].length;
     this.replaceBlock(block,'<'+tag+'>'+inline(content||'')+(content?'':'<br>')+'</'+tag+'>',content.length);
     this.updateEmpty();this.notify({inputType:'format'});return;
    }
    const textNode=selection?.anchorNode;
    if(block&&selection?.isCollapsed&&textNode?.nodeType===3&&!textNode.parentElement.closest('code,pre,a')&&/(\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|`[^`]+`)/.test(textNode.nodeValue)){
     const probe=document.createElement('span');probe.innerHTML=inline(textNode.nodeValue.slice(0,selection.anchorOffset));const offset=probe.textContent.length;
     const marker='inline-'+Date.now();const html='<span data-md-inline="'+marker+'">'+inline(textNode.nodeValue)+'</span>';this.transforming=true;const range=document.createRange();range.selectNode(textNode);selection.removeAllRanges();selection.addRange(range);document.execCommand('insertHTML',false,html);const inserted=this.element.querySelector('[data-md-inline="'+marker+'"]');if(inserted){inserted.removeAttribute('data-md-inline');setCaret(inserted,offset);}this.transforming=false;
    }
   }
   this.rememberSelection();this.notify(event);
  }
 }
 const api={Editor,toHTML,toMarkdown,inline,parseFenceLine};global.MarkdownEditor=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
