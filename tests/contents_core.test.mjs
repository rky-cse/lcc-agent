import test from 'node:test';
import assert from 'node:assert/strict';
import {originalPoint,rectangle} from '../library_claim/web/contents_core.mjs';
const frame={id:'new',width:1600,height:900};
const image={complete:true,currentSrc:'http://localhost/api/frames/new',naturalWidth:1600,naturalHeight:900};
const box={left:10,top:20,width:800,height:450};
test('image belonging to the previous frame cannot produce coordinates even at identical dimensions',()=>{
 assert.throws(()=>originalPoint(frame,{...image,currentSrc:'http://localhost/api/frames/old'},box,{clientX:410,clientY:245},image.currentSrc));
 assert.throws(()=>originalPoint(frame,{...image,complete:false},box,{clientX:410,clientY:245},image.currentSrc));
});
test('display coordinates map to encoded original pixels and clamp to legal edges',()=>{
 assert.deepEqual(originalPoint(frame,image,box,{clientX:410,clientY:245},image.currentSrc),[800,450]);
 assert.deepEqual(originalPoint(frame,image,box,{clientX:810,clientY:470},image.currentSrc),[1599,899]);
 assert.deepEqual(originalPoint(frame,image,box,{clientX:0,clientY:0},image.currentSrc),[0,0]);
});
test('rotated dimensions, zero-sized images and nonfinite pointers cannot annotate originals',()=>{
 assert.throws(()=>originalPoint(frame,{...image,naturalWidth:900,naturalHeight:1600},box,{clientX:1,clientY:2},image.currentSrc));
 assert.throws(()=>originalPoint(frame,image,{...box,width:0},{clientX:1,clientY:2},image.currentSrc));
 assert.throws(()=>originalPoint(frame,image,box,{clientX:NaN,clientY:2},image.currentSrc));
});
test('reverse corner order is valid while zero-area and incomplete rectangles stay unavailable',()=>{
 assert.deepEqual(rectangle([[400,600],[20,30]]),[20,30,400,600]);
 for(const value of [[],[[1,1]],[[2,2],[2,3]],[[1,1],[NaN,3]]])assert.throws(()=>rectangle(value));
});
