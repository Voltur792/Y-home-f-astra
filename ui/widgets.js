(() => {
    'use strict';
    const $ = id => document.getElementById(id);
    const fields = ['title','background','foreground','accent','transparency','width','font_size','refresh_seconds'];
    const flags = ['enabled','on_top','rounded','bars'];
    const defaults = {title:'Мой дом',background:'#25243b',foreground:'#ffffff',accent:'#a78bfa',transparency:10,width:340,font_size:13,refresh_seconds:1,enabled:true,on_top:false,rounded:true,bars:true};
    let sources = [], widgets = [], items = [], editing = '', pending = false, loaded = false;
    let imageId = '', imagePreview = '', imageGeneration = 0;
    const node = (tag, text='', cls='') => { const n=document.createElement(tag); n.textContent=text; n.className=cls; return n; };
    const id = key => 'widget-' + key.replaceAll('_','-');
    async function call(method, params={}) {
        if (!window.astra?.callBackend) throw Error('Откройте вкладку внутри Astra.');
        const result=await window.astra.callBackend('yandex_home_'+method,params);
        if (!result || result.error) throw Error(result?.error || 'Нет ответа от плагина.');
        return result;
    }
    async function prepareImage(file) {
        let bitmap;
        try { bitmap=await createImageBitmap(file,{imageOrientation:'from-image'}); }
        catch { throw Error('Не удалось прочитать картинку. Выберите PNG, JPG или WebP.'); }
        try {
            const scale=Math.min(1,1920/Math.max(bitmap.width,bitmap.height));
            let canvas=document.createElement('canvas');
            canvas.width=Math.max(1,Math.round(bitmap.width*scale));
            canvas.height=Math.max(1,Math.round(bitmap.height*scale));
            canvas.getContext('2d').drawImage(bitmap,0,0,canvas.width,canvas.height);
            // Only a compact copy crosses Astra's message bridge. The original
            // file has no size cap, and transparent image pixels are preserved.
            while(true) {
                const blob=await new Promise(resolve=>canvas.toBlob(resolve,'image/webp',.92));
                if(!blob)throw Error('Не удалось подготовить фон. Выберите другую картинку.');
                if(blob.size<=1536*1024) {
                    return await new Promise((resolve,reject)=>{
                        const reader=new FileReader();reader.onload=()=>resolve(reader.result);
                        reader.onerror=()=>reject(Error('Не удалось прочитать картинку.'));reader.readAsDataURL(blob);
                    });
                }
                const smaller=document.createElement('canvas');
                smaller.width=Math.max(1,Math.round(canvas.width*.75));
                smaller.height=Math.max(1,Math.round(canvas.height*.75));
                smaller.getContext('2d').drawImage(canvas,0,0,smaller.width,smaller.height);
                canvas.width=canvas.height=1;canvas=smaller;
            }
        } finally { bitmap.close(); }
    }
    function message(text,bad=false) { $('widget-message').textContent=text; $('widget-message').className='message'+(bad?' error':''); }
    function lock(value) {
        pending=value;
        $('widget-form').setAttribute('aria-busy',String(value));
        $('widgets').querySelectorAll('input,select,button').forEach(n=>n.disabled=value);
    }
    function settings() {
        const result={items:items.map(i=>({...i})),background_image:imageId};
        for(const key of fields) result[key]=['transparency','width','font_size','refresh_seconds'].includes(key)?Number($(id(key)).value):$(id(key)).value;
        for(const key of flags) result[key]=$(id(key)).checked;
        return result;
    }
    function preview() {
        const s=settings(), card=node('div','','widget-preview');
        card.style.backgroundColor=s.background; card.style.color=s.foreground;
        if(imagePreview){card.style.backgroundImage='url("'+imagePreview+'")';card.style.backgroundSize='cover';card.style.backgroundPosition='center';}
        card.style.fontSize=s.font_size+'px'; card.style.opacity=String(1-s.transparency/100);
        card.style.width=s.width+'px'; card.style.maxWidth='100%';
        card.style.borderRadius=s.rounded?'12px':'0'; card.style.setProperty('--widget-accent',s.accent);
        card.append(node('h4',s.title||'Мой дом'));
        for(const item of items) {
            const source=sources.find(x=>x.key===item.key);
            const reading=source?.reading;
            const row=node('div','','widget-reading'), line=node('div','','widget-reading-line');
            line.append(node('span',item.label||source?.label||'Недоступный показатель'),node('strong',reading?.text||'Нет данных'));
            row.append(line);
            if(s.bars && reading?.progress!=null) {
                const bar=node('progress'); bar.max=100; bar.value=reading.progress;
                bar.setAttribute('aria-label',item.label||source.label); row.append(bar);
            }
            card.append(row);
        }
        if(!items.length) card.append(node('p','Добавьте показатели из списка.'));
        $('widget-preview').replaceChildren(card);
        $('widget-transparency-value').textContent=s.transparency+'%';
        $('widget-background-remove').hidden=!imageId;
    }
    function renderItems() {
        const container=$('widget-items'); container.replaceChildren();
        items.forEach((item,index)=>{
            const source=sources.find(x=>x.key===item.key), row=node('div','','widget-item');
            const label=node('input');label.type='text';label.maxLength=80;label.value=item.label;
            label.placeholder=source?.label||'Подпись показателя';label.setAttribute('aria-label','Подпись: '+(source?.label||'показатель'));
            label.oninput=()=>{item.label=label.value;preview();};row.append(label);
            for(const [text,description,handler] of [
                ['↑','Переместить показатель вверх',()=>{if(index){[items[index-1],items[index]]=[items[index],items[index-1]];renderItems();}}],
                ['↓','Переместить показатель вниз',()=>{if(index+1<items.length){[items[index+1],items[index]]=[items[index],items[index+1]];renderItems();}}],
                ['×','Удалить показатель',()=>{items.splice(index,1);renderItems();}]
            ]){const b=node('button',text,'btn compact');b.type='button';b.setAttribute('aria-label',description);b.onclick=handler;row.append(b);}
            container.append(row);
        });
        preview();
    }
    function fill(widget={...defaults,items:[]}) {
        editing=widget.id||'';items=(widget.items||[]).map(i=>({...i}));
        for(const key of fields) $(id(key)).value=widget[key]??defaults[key];
        for(const key of flags) $(id(key)).checked=widget[key]??defaults[key];
        const generation=++imageGeneration;
        imageId=widget.background_image||'';imagePreview='';$('widget-background-file').value='';
        if(imageId)call('widget_image_preview',{image_id:imageId}).then(result=>{
            if(generation===imageGeneration){imagePreview=result.preview;preview();}
        }).catch(e=>{if(generation===imageGeneration)message('Не удалось загрузить фон: '+e.message,true);});
        $('widget-form-title').textContent=editing?'Настроить виджет':'Новый виджет';
        $('widget-save').textContent=editing?'Применить изменения':'Создать виджет';
        $('widget-cancel').hidden=!editing;renderItems();
    }
    function renderState(state) {
        widgets=state.widgets;
        $('widgets-availability').textContent=state.available?'До 8 виджетов, в каждом до 12 показателей. Окна работают, пока включён плагин в Astra.':'Настольные виджеты доступны в Windows.';
        const list=$('widget-list');list.replaceChildren();
        if(!widgets.length) list.append(node('p','Виджетов пока нет','input-help'));
        for(const widget of widgets){
            const card=node('article','','voice-card');card.append(node('h4',widget.title,'scenario-name'),node('p',widget.items.length+' показателей · '+(widget.enabled?(widget.running?'На рабочем столе':'Запускается'):'Скрыт'),'input-help'));
            if(widget.error)card.append(node('p',widget.error,'message error'));
            const buttons=node('div','','voice-buttons');
            for(const [text,handler] of [
                ['Настроить',()=>{if(!pending){fill(widget);message('');}}],
                [widget.enabled?'Скрыть':'Показать',()=>change(widget,{enabled:!widget.enabled})],
                ['Вернуть позицию',()=>change(widget,{reset_position:true})],
                ['Удалить',()=>{
                    if(card.querySelector('.voice-delete-confirm')||pending)return;
                    const confirmation=node('div','','voice-delete-confirm');confirmation.append(node('span','Удалить виджет?'));
                    const yes=node('button','Удалить','btn compact'),no=node('button','Отмена','btn compact');yes.type=no.type='button';
                    yes.onclick=()=>change(widget,{delete:true});no.onclick=()=>confirmation.remove();confirmation.append(yes,no);card.append(confirmation);yes.focus();
                }]
            ]){const b=node('button',text,'btn compact');b.type='button';b.onclick=handler;buttons.append(b);}
            card.append(buttons);list.append(card);
        }
    }
    async function change(widget,params){
        if(pending)return;lock(true);
        try{renderState(await call('widget_change',{id:widget.id,...params}));if(params.delete&&editing===widget.id)fill();message('Сохранено.');}
        catch(e){message(e.message,true);}finally{lock(false);}
    }
    async function show(force=false){
        if(pending||(loaded&&!force))return;lock(true);message('Загрузка показателей…');
        try{
            const [catalog,state]=await Promise.all([call('widget_catalog'),call('widgets_state')]);
            sources=catalog.sources;const select=$('widget-source');select.replaceChildren();
            const first=node('option','Выберите показатель');first.value='';select.append(first);
            for(const [kind,title] of [['device','Датчики и устройства дома'],['system','Компьютер']]){
                const group=node('optgroup');group.label=title;
                for(const source of sources.filter(s=>s.source===kind)){const o=node('option',(source.room?source.room+' · ':'')+source.label);o.value=source.key;group.append(o);}
                select.append(group);
            }
            renderState(state);loaded=true;renderItems();
            message(catalog.device_error?'Нет связи с Яндексом: '+catalog.device_error+'. Доступны показатели компьютера.':catalog.system_note,!!catalog.device_error);
        }catch(e){message(e.message,true);}finally{lock(false);}
    }
    document.addEventListener('DOMContentLoaded',()=>{
        fill();
        for(const key of [...fields,...flags])$(id(key)).addEventListener('input',preview);
        $('widgets-refresh').onclick=()=>show(true);
        $('widget-cancel').onclick=()=>{fill();message('');};
        $('widget-background-remove').onclick=()=>{++imageGeneration;imageId='';imagePreview='';$('widget-background-file').value='';preview();message('Фон будет однотонным после сохранения.');};
        $('widget-background-file').onchange=async()=>{
            const file=$('widget-background-file').files[0];if(!file||pending)return;
            if(!['image/png','image/jpeg','image/webp'].includes(file.type)){message('Выберите PNG, JPG или WebP.',true);$('widget-background-file').value='';return;}
            const generation=++imageGeneration;lock(true);message('Подготавливаем картинку…');
            try{
                const data=await prepareImage(file);
                const result=await call('widget_image_upload',{data});
                if(generation===imageGeneration){imageId=result.image_id;imagePreview=result.preview;preview();message('Картинка выбрана. Сохраните виджет, чтобы применить фон.');}
            }catch(e){if(generation===imageGeneration)message(e.message,true);}
            finally{$('widget-background-file').value='';lock(false);}
        };
        $('widget-add-source').onclick=()=>{
            const key=$('widget-source').value;
            if(!key){message('Выберите показатель.',true);return;}
            if(items.some(i=>i.key===key)){message('Показатель уже добавлен.',true);return;}
            if(items.length>=12){message('В одном виджете может быть до 12 показателей.',true);return;}
            items.push({key,label:''});renderItems();message('');
        };
        $('widget-form').onsubmit=async event=>{
            event.preventDefault();if(pending)return;const value=settings();lock(true);message('Сохраняем…');
            try{renderState(await call('widget_save',{id:editing,settings:value}));fill();message('Виджет сохранён. Изменения применяются сразу.');}
            catch(e){message(e.message,true);}finally{lock(false);}
        };
        setInterval(async()=>{
            if(pending||!loaded||!$('widgets').classList.contains('active'))return;
            try{const state=await call('widgets_state');if(!pending)renderState(state);}catch(e){message(e.message,true);}
        },5000);
    });
    window.HomeWidgets={show,reset:()=>{loaded=false;sources=[];fill();}};
})();
