import streamlit as st

def render_step(spec, flow_state, simulation_mode):
    step = spec['user_flow'][flow_state['current_step']]
    audience = flow_state.get('audience', 'self')
    
    # Personalize prompt
    prompt = step['prompt']
    if isinstance(prompt, dict):
        prompt = prompt.get(audience, prompt.get('self', ''))
    for key in ['person_a_name', 'person_b_name']:
        value = flow_state['answers'].get(key, key)
        prompt = prompt.replace(f"[{key}]", value)
    
    st.subheader(prompt)
    
    if step['type'] == 'single_select':
        options = step['options']
        for key in ['person_a_name', 'person_b_name']:
            value = flow_state['answers'].get(key, key)
            options = [opt.replace(f"[{key}]", value) for opt in options]
        selected = st.radio("Select:", options, key=f"select_{flow_state['current_step']}")
        if st.button("Next", key=f"next_{flow_state['current_step']}"):
            # Find the original option key
            for opt in step['options']:
                opt_personalized = opt
                for key in ['person_a_name', 'person_b_name']:
                    opt_personalized = opt_personalized.replace(f"[{key}]", flow_state['answers'].get(key, key))
                if opt_personalized == selected:
                    branch = step['branches'][opt]
                    break
            for k, v in branch.get('set', {}).items():
                flow_state['answers'][k] = v
            if 'flow_mode' in k:
                flow_state['mode'] = v
            flow_state['current_step'] = branch['next']
            st.rerun()
    
    elif step['type'] == 'text':
        field = step['field']
        value = st.text_input("Enter:", value=flow_state['answers'].get(field, ""), key=field)
        if st.button("Next", key=f"next_{flow_state['current_step']}"):
            flow_state['answers'][field] = value
            flow_state['current_step'] = step['next']
            st.rerun()
    
    elif step['type'] == 'number':
        field = step['field']
        range_min, range_max = step.get('range', [0, 100])
        value = st.number_input("Enter:", min_value=range_min, max_value=range_max,
                               value=flow_state['answers'].get(field, 0), key=field)
        if st.button("Next", key=f"next_{flow_state['current_step']}"):
            flow_state['answers'][field] = value
            flow_state['current_step'] = step['next']
            st.rerun()
    
    elif step.get('prompts'):
        for prompt in step['prompts']:
            field = prompt['field']
            prompt_text = prompt['prompt']
            for key in ['person_a_name', 'person_b_name']:
                prompt_text = prompt_text.replace(f"[{key}]", flow_state['answers'].get(key, key))
            if prompt['type'] == 'text':
                flow_state['answers'][field] = st.text_input(prompt_text, value=flow_state['answers'].get(field, ""), key=field)
        if st.button("Next", key=f"next_{flow_state['current_step']}"):
            flow_state['current_step'] = step['next']
            st.rerun()
    
    elif step.get('group'):
        render_ui_groups(spec, flow_state, step['group'], simulation_mode)

def render_ui_groups(spec, flow_state, group_ids, simulation_mode):
    if 'grouped_answers' not in flow_state:
        flow_state['grouped_answers'] = {}
    
    selected_modules = []
    for mod in spec.get('modules', []):
        if not mod.get('condition') or flow_state['answers'].get(mod['condition']['field']) == mod['condition']['equals']:
            if mod.get('default_selected') or st.checkbox(mod['label'], value=mod.get('default_selected'), key=f"mod_{mod['id']}"):
                selected_modules.append(mod['id'])
    
    for group in spec['ui_groups']:
        if group['id'] not in group_ids or group.get('module') not in selected_modules:
            continue
        if group.get('condition') and flow_state['answers'].get(group['condition']['field']) != group['condition']['equals']:
            continue
        with st.expander(group['label'], expanded=True):
            st.write(group['prompt'])
            group_answers = flow_state['grouped_answers'].setdefault(group['id'], {})
            for field in group['fields']:
                label = field.get('label', field['field'])
                kind = field.get('kind', 'currency')
                default = field.get('default', 0)
                step = spec['ui_guidance']['steps'].get(field['field'], 1.0)
                range_vals = spec['ui_guidance']['ranges'].get(field['field'], [0, float('inf')])
                include = st.checkbox(f"Include {label}", value=True, key=f"include_{group['id']}_{field['field']}")
                if include:
                    if kind == 'currency':
                        group_answers[label] = st.number_input(label, min_value=float(range_vals[0]), max_value=float(range_vals[1]),
                                                             value=group_answers.get(label, default), step=step, key=f"{group['id']}_{field['field']}")
                    elif kind == 'boolean':
                        group_answers[label] = st.checkbox(label, value=(group_answers.get(label, default) == field.get('true_value', 'Yes')),
                                                         key=f"{group['id']}_{field['field']}")
                    elif kind == 'select':
                        group_answers[label] = st.selectbox(label, field.get('options', []), index=field.get('options', []).index(group_answers.get(label, default)) if group_answers.get(label) else 0,
                                                           key=f"{group['id']}_{field['field']}")
                else:
                    group_answers[label] = field.get('skip_value', default)
    
    if st.button("Calculate", key="calculate"):
        flow_state['current_step'] = 'results'
        st.rerun()