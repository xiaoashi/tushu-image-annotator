async (page) => {
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.reload();await page.getByRole('heading',{name:'标注工作台',exact:true}).waitFor();
  await page.getByRole('img',{name:/标注画布/}).waitFor();
  await page.locator('.asset-row').filter({hasText:'雪地中的猫.jpg'}).click();
  const svg=page.getByRole('img',{name:'标注画布 雪地中的猫.jpg'});await svg.waitFor();
  const before=await page.evaluate(async()=>{const d=await (await fetch('/api/bootstrap')).json();const a=d.assets.find(a=>a.display_name==='雪地中的猫.jpg');return await(await fetch('/api/assets/'+a.id)).json()});
  await page.getByRole('button',{name:'画框模式',exact:true}).click();
  const stage=await svg.boundingBox();await page.mouse.move(stage.x+stage.width*.35,stage.y+stage.height*.35);await page.mouse.down();await page.mouse.move(stage.x+stage.width*.55,stage.y+stage.height*.55,{steps:6});await page.mouse.up();
  await page.waitForFunction(async(previous)=>{const d=await (await fetch('/api/bootstrap')).json();const a=d.assets.find(a=>a.display_name==='雪地中的猫.jpg');const detail=await(await fetch('/api/assets/'+a.id)).json();return detail.boxes.length===previous+1},before.boxes.length);
  await page.getByRole('button',{name:'撤销 ⌘ Z',exact:true}).click();
  await page.waitForFunction(async(previous)=>{const d=await (await fetch('/api/bootstrap')).json();const a=d.assets.find(a=>a.display_name==='雪地中的猫.jpg');const detail=await(await fetch('/api/assets/'+a.id)).json();return detail.boxes.length===previous},before.boxes.length);
  await page.getByRole('textbox',{name:'搜索图片名称'}).fill('no-such-image-should-never-match');
  await page.waitForFunction(()=>document.querySelectorAll('.asset-row').length===0);
  const disabled=await page.getByRole('button',{name:'确认并完成复核 ⌘ ↵',exact:true}).isDisabled();if(!disabled)throw Error('Invisible current asset remains actionable');
  await page.getByRole('textbox',{name:'搜索图片名称'}).fill('');
  await page.locator('.asset-row').filter({hasText:'向日葵与蜜蜂.jpg'}).click();
  await page.getByRole('img',{name:'标注画布 向日葵与蜜蜂.jpg'}).waitFor();
  await page.getByRole('button',{name:'选择模式',exact:true}).click();
  return {draw_save_and_undo:true,zero_filter_blocks_actions:disabled,page_errors:errors,viewport:await page.evaluate(()=>({width:innerWidth,scrollWidth:document.documentElement.scrollWidth}))};
}
