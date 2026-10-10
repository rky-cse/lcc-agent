// Read-only polling independent of camera uploads. Ignore late sweep/page responses.
export class InventoryPoller {
  constructor({fetchSnapshot, changed, failed, delay=2000, setTimer=(fn,ms)=>setTimeout(fn,ms), clearTimer=id=>clearTimeout(id)}) {
    Object.assign(this,{fetchSnapshot,changed,failed,delay,setTimer,clearTimer});
    this.epoch=0; this.sweepId=null; this.offset=0; this.revision=-1; this.running=false;
  }
  watch(id) {
    if(id===this.sweepId && this.running) return;
    this.select(id, id===this.sweepId ? this.offset : 0);
  }
  select(id,offset=0) {
    const previous=this.sweepId;
    this.stop(); this.sweepId=id; this.offset=offset;
    if(id!==previous) this.revision=-1;
    this.lastPayload=null; this.hadError=false;
    this.changed(null);
    if(!id) return;
    this.running=true; void this.poll(this.epoch);
  }
  stop() {
    this.running=false; ++this.epoch; this.clearTimer(this.timer);
    this.controller?.abort(); this.timer=null;
    this.clearTimer(this.deadline);
  }
  async poll(epoch) {
    if(!this.running || epoch!==this.epoch) return;
    const controller=new AbortController(); this.controller=controller;
    const timeout=this.setTimer(()=>controller.abort(),10000);
    this.deadline=timeout;
    try {
      const data=await this.fetchSnapshot(this.sweepId,this.offset,controller.signal);
      if(epoch!==this.epoch || !this.running) return;
      if(data.sweep_id!==this.sweepId || data.page_offset!==this.offset || !Number.isSafeInteger(data.revision)
          || data.revision<0 || !Array.isArray(data.rows)) throw new Error('Invalid inventory response');
      if(data.revision<this.revision) throw new Error('Older inventory revision received');
      this.revision=data.revision;
      const payload=JSON.stringify(data);
      if(payload!==this.lastPayload || this.hadError) this.changed(data);
      this.lastPayload=payload; this.hadError=false;
    } catch(error) {
      if(epoch===this.epoch && this.running) { this.hadError=true; this.failed(error); }
    } finally {
      this.clearTimer(timeout);
      if(epoch===this.epoch && this.running) this.timer=this.setTimer(()=>void this.poll(epoch),this.delay);
    }
  }
}

export function renderInventory(document,data) {
  const $=id=>document.getElementById(id);
  $('inventory-rows').replaceChildren(); $('inventory-export').hidden=!data;
  $('inventory-prev').disabled=true; $('inventory-next').disabled=true;
  if(!data) {
    $('inventory-summary').textContent='Waiting for inventory data.';
    $('inventory-state').textContent='Reviewed detection results will appear after the inventory loads.';
    $('inventory-page').textContent=''; return;
  }
  $('inventory-summary').textContent=`Revision ${data.revision} · ${data.assigned_track_count} assigned tracks · ${data.owned_assigned_track_count} owned · ${data.review_count} review entries · total books unknown`;
  $('inventory-state').textContent=data.detection_import_count ? 'Provisional results from reviewed detection imports. Coverage is unverified.' : 'No detection results imported. Camera recognition is not connected yet.';
  $('inventory-export').href=`/api/sweeps/${encodeURIComponent(data.sweep_id)}/inventory/export`;
  for(const row of data.rows) {
    const tr=document.createElement('tr');
    const values=[row.kind==='book' ? (row.title || 'Unidentified book') : 'Needs review',row.shelf || 'Unknown shelf',
      row.kind==='book' ? (row.owned ? 'Included' : 'Excluded') : 'Unresolved',row.reason];
    for(const value of values) { const td=document.createElement('td'); td.textContent=value; tr.append(td); }
    const td=document.createElement('td'), link=document.createElement('a');
    link.href=`/api/frames/${encodeURIComponent(row.frame_ref)}`; link.target='_blank'; link.rel='noopener';
    link.textContent=row.kind==='book' ? `Original · ${row.observation_count} observations` : 'Original';
    td.append(link); tr.append(td); $('inventory-rows').append(tr);
  }
  $('inventory-page').textContent=data.total_rows ? `Rows ${data.page_offset+1}–${Math.min(data.page_offset+data.rows.length,data.total_rows)} of ${data.total_rows}` : 'No inventory rows yet.';
  $('inventory-prev').disabled=data.page_offset===0;
  $('inventory-next').disabled=data.page_offset+data.page_limit>=data.total_rows;
}
