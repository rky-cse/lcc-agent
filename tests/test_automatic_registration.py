import io
import random
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone
from PIL import Image
from library_claim.capture_store import FrameStore,CaptureInput,StorageLimits
from library_claim.automatic_registration import acquire_links


class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=FrameStore(Path(temp.name),StorageLimits(min_short_edge=0,min_long_edge=0))
    def save(self,image,name):
        out=io.BytesIO();image.save(out,'PNG')
        return self.store.save(CaptureInput(sweep_id='unit-shelf',upload_id=name,captured_at=datetime.now(timezone.utc),media_sequence=0 if name=='anchor' else 1,source='file_import',synthetic=True),out.getvalue()).id
    def test_feature_alignment_returns_only_unaccepted_review_links(self):
        rng=random.Random(147);data=bytes(rng.randrange(256) for _ in range(500*500))
        anchor=Image.frombytes('L',(500,500),data).convert('RGB')
        current=anchor.transform(anchor.size,Image.Transform.AFFINE,(1,0,-10,0,1,-5))
        old=self.save(anchor,'anchor');new=self.save(current,'current')
        polygon=[(150,150),(250,150),(250,350),(150,350)]
        result=acquire_links(self.store,dict(frame_ref=new,observations=[dict(id='new',polygon_px=[(x+10,y+5) for x,y in polygon])]),
            [dict(frame_ref=old,observations=[dict(id='old',track_id='book',polygon_px=polygon)])])
        self.assertEqual(result['status'],'review_required');self.assertFalse(result['accepted'])
        self.assertTrue(result['links']);self.assertEqual(result['links'][0]['proposed_track_id'],'book')
        self.assertFalse(result['links'][0]['accepted']);self.assertFalse(result['proofs'][0]['physical_assertions_verified'])
    def test_no_texture_or_anchor_never_creates_a_new_copy(self):
        ref=self.save(Image.new('RGB',(500,500),'white'),'anchor')
        self.assertEqual(acquire_links(self.store,dict(frame_ref=ref,observations=[]),[])['status'],'no_anchor')
        result=acquire_links(self.store,dict(frame_ref=ref,observations=[]),[dict(frame_ref=ref,observations=[])])
        self.assertFalse(result['accepted']);self.assertEqual(result['links'],[])


if __name__=='__main__':unittest.main()
