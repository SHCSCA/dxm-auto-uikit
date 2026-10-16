"""原生属性控件的只读采样；没有调用处理器、打开分区或接口请求。"""


EDITOR_CONTROL_INVENTORY_SCRIPT = r"""({fields,sections,limits}) => {
  const result={schema:'dxm.editor_control_dom.v1',collected:false,url:location.href,
    document_time_origin:performance.timeOrigin,root_count:0,sections:[],fields:[],missing:[]};
  const missing=code=>{if(!result.missing.includes(code))result.missing.push(code);};
  const visible=el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el);return r.width>0&&r.height>0&&s.display!=='none'&&s.visibility!=='hidden';};
  const all=(root,selector)=>[...root.querySelectorAll(selector)];
  const controls='input,textarea,select,[contenteditable="true"]';
  const disabled=el=>!!el.disabled||el.matches(':disabled')||el.getAttribute('aria-disabled')==='true';
  const describe=el=>({tag:el.tagName.toLowerCase(),id:el.id||null,name:el.getAttribute('name'),
    type:el.getAttribute('type'),visible:visible(el),disabled:disabled(el),
    read_only:!!el.readOnly,content_editable:el.getAttribute('contenteditable')==='true'});
  try{
    const roots=all(document,'.product-add-wrapper');result.root_count=roots.length;
    if(roots.length!==1||!visible(roots[0])){missing('EDITOR_ROOT_NOT_UNIQUE_VISIBLE');return result;}
    const root=roots[0];
    result.sections=sections.map(section=>{
      const nodes=section.anchor?all(root,'[id]').filter(el=>el.id===section.anchor):[];
      return {code:section.code,anchor:section.anchor,match_count:nodes.length,
        visible_count:nodes.filter(visible).length};
    });
    for(const field of fields){
      const row={field_key:field.field_key,ui_binding:field.ui_binding,match_count:0,control:null,
        raw_value:null,value_observed:false,value_kind:null,options:null,section_bound:false,missing:[]};
      const fail=code=>{if(!row.missing.includes(code))row.missing.push(code);};
      // 原生 name/id 必须完整精确匹配；标签、任意 marker 和 JSON 展示值不参与定位。
      const identities=new Set([field.field_key,'form_item_'+field.field_key]);
      if(field.field_key==='title'){identities.add('subject');identities.add('form_item_subject');}
      const matches=all(root,controls).filter(el=>!el.closest('[role="dialog"],.ant-modal')
        &&(identities.has(el.id)||el.getAttribute('name')===field.field_key
          ||field.field_key==='title'&&el.getAttribute('name')==='subject'));
      row.match_count=matches.length;
      if(matches.length!==1){fail(matches.length?'CONTROL_IDENTITY_AMBIGUOUS':'CONTROL_NATIVE_IDENTITY_MISSING');result.fields.push(row);continue;}
      const el=matches[0],kind=(el.getAttribute('type')||'text').toLowerCase();row.control=describe(el);
      if(!visible(el)){fail('CONTROL_NOT_VISIBLE');result.fields.push(row);continue;}
      if(disabled(el))fail('CONTROL_DISABLED');
      if(el.readOnly)fail('CONTROL_READ_ONLY');
      const section=sections.find(item=>item.code===field.section),bound=section?.anchor
        ?all(root,'[id]').filter(node=>node.id===section.anchor):[];
      row.section_bound=bound.length===1&&visible(bound[0])&&bound[0].contains(el);
      if(!row.section_bound)fail('SECTION_CONTROL_BOUNDARY_UNPROVEN');
      let value;
      if(el.tagName==='INPUT'){
        if(kind==='checkbox'){value=el.checked;row.value_kind='checkbox_boolean';}
        else if(['text','search','url','tel','email','number'].includes(kind)){value=el.value;row.value_kind='native_input_value';}
        else {fail('CONTROL_TYPE_UNREVIEWED');result.fields.push(row);continue;}
      }else if(el.tagName==='TEXTAREA'){value=el.value;row.value_kind='native_textarea_value';}
      else if(el.tagName==='SELECT'){
        const options=[...el.options];
        if(options.length>limits.max_options){fail('CONTROL_OPTION_LIMIT_EXCEEDED');result.fields.push(row);continue;}
        row.options=options.map(option=>({value:option.value,selected:option.selected,
          disabled:option.disabled||!!option.parentElement?.disabled}));
        value=el.multiple?[...el.selectedOptions].map(option=>option.value):el.value;
        row.value_kind=el.multiple?'native_multi_select_values':'native_select_value';
        if(row.options.some((option,index)=>row.options.findIndex(other=>other.value===option.value)!==index))fail('OPTION_VALUE_IDENTITY_AMBIGUOUS');
      }else if(el.getAttribute('contenteditable')==='true'){
        if(el.children.length){fail('RICH_CONTENT_RESTORE_UNPROVEN');result.fields.push(row);continue;}
        value=el.textContent;row.value_kind='plain_contenteditable_text';
      }else {fail('CONTROL_TYPE_UNREVIEWED');result.fields.push(row);continue;}
      if(JSON.stringify(value).length>limits.max_value_chars){fail('CONTROL_VALUE_LIMIT_EXCEEDED');result.fields.push(row);continue;}
      row.raw_value=value;row.value_observed=true;
      result.fields.push(row);
    }
    result.collected=true;
  }catch(error){missing('EDITOR_CONTROL_DOM_READ_FAILED');result.error_type=String(error?.name||'UnknownError');}
  return result;
}"""
