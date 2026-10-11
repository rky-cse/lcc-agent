"""Bounded correspondence acquisition; every link still requires physical review."""
import io
import random
from PIL import Image
from .matching import iou
from .planar import inside,area


def hull(points):
    points=sorted(set(tuple(map(float,p)) for p in points))
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower=[];upper=[]
    for p in points:
        while len(lower)>=2 and cross(lower[-2],lower[-1],p)<=0:lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper)>=2 and cross(upper[-2],upper[-1],p)<=0:upper.pop()
        upper.append(p)
    return lower[:-1]+upper[:-1]


def acquire_links(store,current,anchors):
    """Harris corners, normalized patches and held-out homography checks.

    Large rotation/perspective changes and repetitive patterns may fail matching;
    failures stay unresolved. No shelf, lens or coplanarity assertion is inferred.
    """
    if not anchors:return dict(status='no_anchor',links=[],accepted=False)
    import numpy as np
    def image(ref):
        frame=store.get(ref)
        if frame.exif_orientation not in (None,1):raise ValueError('unsupported registration orientation')
        with Image.open(io.BytesIO(store.read(ref))) as raw:
            grey=raw.convert('L');scale=min(1,700/max(grey.size));grey.thumbnail((700,700))
            return np.asarray(grey,dtype=np.float64)/255,scale
    def features(data):
        gy,gx=np.gradient(data)
        def smooth(v):return sum(np.roll(np.roll(v,dy,axis=0),dx,axis=1) for dy in (-1,0,1) for dx in (-1,0,1))/9
        xx,yy,xy=smooth(gx*gx),smooth(gy*gy),smooth(gx*gy)
        score=xx*yy-xy*xy-.04*(xx+yy)**2;score[:8]=0;score[-8:]=0;score[:,:8]=0;score[:,-8:]=0
        points=[];descriptors=[]
        for index in np.argsort(score.ravel())[-3000:][::-1]:
            y,x=divmod(int(index),data.shape[1])
            if score[y,x]<=1e-7:break
            if any((x-a)**2+(y-b)**2<64 for a,b in points):continue
            patch=data[y-5:y+6,x-5:x+6].ravel();std=patch.std()
            if std<.03:continue
            points.append((x,y));descriptors.append((patch-patch.mean())/std)
            if len(points)>=250:break
        return np.asarray(points,dtype=np.float64),np.asarray(descriptors)
    def fit(a,b):
        a=a/700;b=b/700;rows=[];rhs=[]
        for (x,y),(u,v) in zip(a,b):
            rows.extend([[x,y,1,0,0,0,-u*x,-u*y],[0,0,0,x,y,1,-v*x,-v*y]]);rhs.extend([u,v])
        values,_,rank,_=np.linalg.lstsq(np.asarray(rows),np.asarray(rhs),rcond=None)
        if rank<8:return None
        h=np.append(values,1).reshape(3,3)
        return np.diag([700,700,1])@h@np.diag([1/700,1/700,1])
    def project(h,points):
        mapped=np.column_stack([points,np.ones(len(points))])@h.T
        with np.errstate(divide='ignore',invalid='ignore'):return mapped[:,:2]/mapped[:,2:]
    source,ss=image(current['frame_ref']);a,ad=features(source);links=[];proofs=[]
    if len(a)<16:return dict(status='insufficient_features',links=[],accepted=False)
    for anchor in anchors[-3:]:
        target,ts=image(anchor['frame_ref']);b,bd=features(target)
        if len(b)<16:continue
        distances=((ad[:,None,:]-bd[None,:,:])**2).mean(axis=2)
        best=np.argsort(distances,axis=1)[:,:2];reverse=np.argmin(distances,axis=0)
        pairs=[(i,int(j)) for i,(j,k) in enumerate(best) if reverse[j]==i and distances[i,j]<.45 and distances[i,j]<.65*distances[i,k]]
        if len(pairs)<16:continue
        aa=np.asarray([a[i] for i,j in pairs]);bb=np.asarray([b[j] for i,j in pairs]);training=np.arange(len(aa))%4!=0
        ta,tb=aa[training],bb[training];rng=random.Random(0);mask=None;count=0
        for _ in range(100):
            selection=rng.sample(range(len(ta)),4);h=fit(ta[selection],tb[selection])
            if h is None:continue
            residual=np.linalg.norm(project(h,ta)-tb,axis=1);inliers=np.isfinite(residual)&(residual<=3)
            if int(inliers.sum())>count:mask=inliers;count=int(inliers.sum())
        if count<12:continue
        h=fit(ta[mask],tb[mask])
        if h is None or float(np.linalg.det(h[:2,:2]))<=0:continue
        errors=np.linalg.norm(project(h,aa[~training])-bb[~training],axis=1)
        if len(errors)<4 or not np.isfinite(errors).all() or np.median(errors)>3 or np.max(errors)>8:continue
        support=hull(ta[mask])
        if len(support)<3 or area(support)<source.size*.08:continue
        proofs.append(dict(anchor_frame_ref=anchor['frame_ref'],matrix=h.tolist(),current_scale=ss,anchor_scale=ts,
            holdout_errors_px=errors.tolist(),inliers=count,physical_assertions_verified=False))
        for observation in current['observations']:
            polygon=np.asarray(observation['polygon_px'])*ss
            if not all(inside(tuple(p),support) for p in polygon):continue
            denominator=polygon[:,0]*h[2,0]+polygon[:,1]*h[2,1]+h[2,2]
            if not (np.all(denominator>1e-6) or np.all(denominator<-1e-6)):continue
            mapped=project(h,polygon)/ts
            for old in anchor['observations']:
                overlap=iou([tuple(map(float,p)) for p in mapped],old['polygon_px'])
                if overlap>=.5:links.append(dict(observation_id=observation['id'],anchor_observation_id=old['id'],
                    proposed_track_id=old['track_id'],iou=overlap,accepted=False,reason='Image alignment proposal; physical shelf/plane/lens review required'))
    return dict(status='review_required' if proofs else 'registration_unavailable',links=links[:256],proofs=proofs,accepted=False)
