from PIL import Image
import os
L=os.path.expanduser('~/launcher/')
o=os.path.expanduser('~/lassets/')
os.makedirs(o,exist_ok=True)
def bg(src,dst):
    im=Image.open(src).convert('RGB').resize((1920,1080),Image.LANCZOS); im.save(o+dst,quality=80)
bg(L+'public/images/jak1/sandover.jpg','bg1.jpg')
bg(L+'src/assets/images/background-jak2.webp','bg2.jpg')
bg(L+'src/assets/images/background-jak3.webp','bg3.jpg')
for s,d in [('jak-tpl','logo1'),('jak-2','logo2'),('jak-3','logo3')]:
    Image.open(L+'src/assets/images/%s.webp'%s).convert('RGBA').save(o+d+'.png',optimize=True)
