import math, sys
if sys.version_info >= (3, 0):
    import builtins
else:
    import __builtin__ as builtins

from panda3d.core import Vec3, PTALVecBase3f, Point3, BitMask32, Vec4, deg2Rad, DepthTestAttrib, RenderAttrib, \
    CullFaceAttrib, ColorBlendAttrib, DepthWriteAttrib


class SceneLight(object):
    """
    Directional light(s) for the deferred renderer
    Because of the way directional lights are implemented (fullscreen quad),
    it's not very logical to have multiple SceneLights, but you can have multiple
    directional lights as part of one SceneLight instance.
    You can add and remove additional lights using add_light() and remove_light()
    This class curently has no properies access :(
    """

    def __init__(self, color=None, direction=None, main_light_name='main', shadow_size=0):
        if not hasattr(builtins, 'deferred_renderer'):
            raise RuntimeError('You need a DeferredRenderer')
        self.__color = {}
        self.__direction = {}
        self.__shadow_size = {}
        self.main_light_name = main_light_name
        if color and direction:
            self.add_light(color=color, direction=direction,
                           name=main_light_name, shadow_size=shadow_size)

    def add_light(self, color, direction, name, shadow_size=0):
        """
        Adds a directional light to this SceneLight
        """
        if len(self.__color) == 0:
            deferred_renderer.set_directional_light(
                color, direction, shadow_size)
            self.__color[name] = Vec3(color)
            self.__direction[name] = Vec3(*direction)
            self.__shadow_size[name] = shadow_size
        else:
            self.__color[name] = Vec3(color)
            self.__direction[name] = Vec3(direction)
            self.__shadow_size[name] = shadow_size
            num_lights = len(self.__color)
            colors = PTALVecBase3f()
            for v in self.__color.values():
                colors.push_back(v)
            directions = PTALVecBase3f()
            for v in self.__direction.values():
                directions.push_back(v)
            deferred_renderer.set_filter_define(
                'final_light', 'NUM_LIGHTS', num_lights)
            deferred_renderer.set_filter_input(
                'final_light', 'light_color', colors)
            deferred_renderer.set_filter_input(
                'final_light', 'direction', directions)

    def remove_light(self, name=None):
        """
        Removes a light from this SceneLight,
        if name is None, the 'main' light (created at init) is removed
        """
        if name is None:
            name = self.main_light_name
        if name in self.__color:
            del self.__color[name]
            del self.__direction[name]
            del self.__shadow_size[name]
            if len(self.__color) == 0:
                deferred_renderer.set_directional_light(
                    (0, 0, 0), (0, 0, 0), 0)
            elif len(self.__color) == 1:
                deferred_renderer.set_filter_define(
                    'final_light', 'NUM_LIGHTS', None)
                last_name = self.__color.keys()[0]
                deferred_renderer.set_directional_light(self.__color[last_name], self.__direction[
                    last_name], self.__shadow_size[last_name])
            else:
                num_lights = len(self.__color)
                colors = PTALVecBase3f()
                for v in self.__color.values():
                    colors.push_back(v)
                directions = PTALVecBase3f()
                for v in self.__direction.values():
                    directions.push_back(v)
                deferred_renderer.set_filter_define(
                    'final_light', 'NUM_LIGHTS', num_lights)
                deferred_renderer.set_filter_input(
                    'final_light', 'light_color', colors)
                deferred_renderer.set_filter_input(
                    'final_light', 'direction', directions)
            return True
        return False

    def set_color(self, color, name=None):
        """
        Sets light color
        """
        if name is None:
            name = self.main_light_name
        self.__color[name] = color
        if len(self.__color) == 1:
            deferred_renderer.set_directional_light(
                color, self.__direction[name], self.__shadow_size[name])
        else:
            colors = PTALVecBase3f()
            for v in self.__color.values():
                colors.push_back(v)
            deferred_renderer.set_filter_input(
                    'final_light', 'light_color', colors)

    def set_direction(self, direction, name=None):
        """
        Sets light direction
        """
        if name is None:
            name = self.main_light_name
        self.__direction[name] = direction
        if len(self.__color) == 1:
            deferred_renderer.set_directional_light(
                self.__color[name], direction, self.__shadow_size[name])
        else:
            directions = PTALVecBase3f()
            for v in self.__direction.values():
                directions.push_back(v)
            deferred_renderer.set_filter_input(
                    'final_light', 'direction', directions)

    def remove(self):
        deferred_renderer.set_filter_define('final_light', 'NUM_LIGHTS', None)
        deferred_renderer.set_directional_light((0, 0, 0), (0, 0, 0), 0)

    def __del__(self):
        try:
            self.remove()
        except:
            pass


class SphereLight(object):
    """
    Point (omni) light for the deferred renderer.
    Create a new SphereLight for each light you want to use,
    remember to keep a reference to the light instance
    the light will be removed by the garbage collector when it goes out of scope

    It is recomended to use properties to configure the light after creation eg.
    l=SphereLight(...)
    l.pos=Point3(...)
    l.color=(r,g,b)
    l.radius= 13
    """

    def __init__(self, color, pos, radius, shadow_size=None, shadow_bias=None):
        if not hasattr(builtins, 'deferred_renderer'):
            raise RuntimeError('You need a DeferredRenderer')
        self.__radius = radius
        self.__color = color
        self.light_id=None
        if shadow_size is None:
            shadow_size=deferred_renderer.shadow_size
        self.geom, self.p3d_light = deferred_renderer.add_point_light(color=color,
                                                                      model="models/sphere",
                                                                      pos=pos,
                                                                      radius=radius,
                                                                      shadow_size=shadow_size)
        self.set_shadow_bias(shadow_bias)

    def attach_to(self, node, offset=(0,0,0)):
        self.light_id=len(deferred_renderer.attached_lights)
        deferred_renderer.attached_lights[self.light_id]=(node, self, Point3(*offset))

    def detach(self):
        if self.light_id:
            del deferred_renderer.attached_lights[self.light_id]

    def set_shadow_size(self, size):
        if size >0:
            self.p3d_light.node().set_shadow_caster(True, size, size)
            self.p3d_light.node().set_camera_mask(BitMask32.bit(13))
            for i in range(6):
                self.p3d_light.node().get_lens(i).set_near_far(0.1, self.__radius)
                self.p3d_light.node().get_lens(i).make_bounds()

            shader=loader.load_shader_GLSL(deferred_renderer.v.format('point_light_shadow'),
                                           deferred_renderer.f.format('point_light_shadow'),
                                           deferred_renderer.shading_setup)
            self.geom.set_shader(shader)
            self.geom.set_shader_input('shadowcaster', self.p3d_light)
            self.set_shadow_bias(self.shadow_bias)
        else:
            self.p3d_light.node().set_shadow_caster(False)
            shader=loader.load_shader_GLSL(deferred_renderer.v.format('point_light'),
                                           deferred_renderer.f.format('point_light'),
                                           deferred_renderer.shading_setup)
            self.geom.set_shader(shader)
            try:
                buff = self.p3d_light.node().get_shadow_buffer(base.win.get_gsg())
                buff.clear_render_textures()
                base.win.get_gsg().get_engine().remove_window(buff)
            except:
                pass

    def set_shadow_bias(self, bias):
        self.shadow_bias=bias
        if bias is not None:
            self.geom.set_shader_input("bias", bias)


    def set_color(self, color):
        """
        Sets light color
        """
        self.geom.set_shader_input("light", Vec4(
            color, self.__radius * self.__radius))
        self.__color = color

    def set_radius(self, radius):
        """
        Sets light radius
        """
        self.geom.set_shader_input("light", Vec4(self.__color, radius * radius))
        self.geom.set_scale(radius)
        self.__radius = radius
        try:
            for i in range(6):
                self.p3d_light.node().get_lens(i).set_near_far(0.1, radius)
        except:
            pass

    def set_pos(self, *args):
        """
        Sets light position,
        you can pass in a NodePath as the first argument to make the pos relative to that node
        """
        if self.geom.is_empty():
            return
        if len(args) < 1:
            return
        elif len(args) == 1:  # one arg, must be a vector
            pos = Vec3(args[0])
        elif len(args) == 2:  # two args, must be a node and  vector
            pos = render.get_relative_point(args[0], Vec3(args[1]))
        elif len(args) == 3:  # vector
            pos = Vec3(args[0], args[1], args[2])
        elif len(args) == 4:  # node and vector?
            pos = render.get_relative_point(
                args[0], Vec3(args[0], args[1], args[2]))
        else:  # something ???
            pos = Vec3(args[0], args[1], args[2])
        #self.geom.setShaderInput("light_pos", Vec4(pos, 1.0))
        self.geom.set_pos(render, pos)
        self.p3d_light.set_pos(render, pos)

    def remove(self):
        self.geom.remove_node()
        try:
            buff = self.p3d_light.node().get_shadow_buffer(base.win.get_gsg())
            buff.clear_render_textures()
            base.win.get_gsg().get_engine().remove_window(buff)
            self.p3d_light.node().set_shadow_caster(False)
        except:
            pass
        if self.light_id and self.light_id in deferred_renderer.attached_lights:
            del deferred_renderer.attached_lights[self.light_id]
        self.p3d_light.remove_node()

    def __del__(self):
        try:
            if not self.geom.is_empty():
                self.remove()
        except:
            pass

    @property
    def pos(self):
        return self.geom.get_pos(render)

    @pos.setter
    def pos(self, p):
        self.set_pos(p)

    @property
    def color(self):
        return self.__color

    @color.setter
    def color(self, c):
        self.set_color(c)

    @property
    def radius(self):
        return self.__radius

    @radius.setter
    def radius(self, r):
        self.set_radius(float(r))


class ConeLight(object):
    """
    Spot light for the deferred renderer.
    Create a new ConeLight for each light you want to use,
    remember to keep a reference to the light instance
    the light will be removed by the garbage collector when it goes out of scope

    You can set the hpr of the light by passing a node or position as the look_at argument

    It is recomended to use properties to configure the light after creation eg.
    l=ConeLight(...)
    l.pos=Point3(...)
    l.color=(r,g,b)
    l.radius= 13
    l.fov=45.0
    l.hpr=Point3(...)
    the lookAt() function can also be used to set a hpr in a different way
    """

    def __init__(self, color, pos, radius, fov, hpr=None,
                look_at=None, exponent=40, shadow_size=0, bias=0.0005):
        if not hasattr(builtins, 'deferred_renderer'):
            raise RuntimeError('You need a DeferredRenderer')
        self.__radius = radius
        self.__color = color
        self.__pos = pos
        self.__hpr = hpr
        self.__fov = fov
        self.__shadow_size = shadow_size
        self.__shadow_bias=bias
        if hpr is None:
            dummy = render.attach_new_node('dummy')
            dummy.set_pos(pos)
            dummy.look_at(look_at)
            hpr = dummy.get_hpr(render)
            dummy.remove_node()
        self.__hpr = hpr
        self.geom, self.p3d_light = deferred_renderer.add_cone_light(color=color,
                                                                     pos=pos,
                                                                     hpr=hpr,
                                                                     exponent=exponent,
                                                                     radius=radius,
                                                                     fov=fov,
                                                                     shadow_size=shadow_size,
                                                                     bias=bias)
    def set_exponent(self, exponent):
        self.p3d_light.node().set_exponent(exponent)

    def set_fov(self, fov):
        """
        Sets the Field of View (in degrees) of the light
        Angles above 120 deg are not recomended,
        Angles above 179 deg are not supported
        """
        if fov > 179.0:
            fov = 179.0
        self.p3d_light.node().get_lens().set_fov(fov)
        # we might as well start from square 1...
        self.geom.remove_node()
        xy_scale = math.tan(deg2Rad(fov * 0.5))
        self.geom = loader.load_model("models/cone")
        self.geom.reparent_to(deferred_renderer.light_root)
        self.geom.set_scale(xy_scale, 1.0, xy_scale)
        self.geom.flatten_strong()
        self.geom.set_scale(self.__radius)
        self.geom.set_pos(self.__pos)
        self.geom.set_hpr(self.__hpr)
        self.geom.set_attrib(DepthTestAttrib.make(RenderAttrib.MLess))
        self.geom.set_attrib(CullFaceAttrib.make(
            set_attrib.MCullCounterClockwise))
        self.geom.setAttrib(ColorBlendAttrib.make(
            set_attrib.MAdd, ColorBlendAttrib.OOne, ColorBlendAttrib.OOne))
        self.geom.set_attrib(DepthWriteAttrib.make(DepthWriteAttrib.MOff))
        self.geom.set_shader(loader.loadShaderGLSL(deferred_renderer.v.format(
            'spot_light'), deferred_renderer.f.format('spot_light'), deferred_renderer.shading_setup))
        try:
            self.geom.set_shader_inputs(light_radius= float(self.__radius),
                                    light_pos= Vec4(self.__pos, 1.0),
                                    light_fov= deg2Rad(fov),
                                    spot= self.p3d_light)
        except AttributeError:
            self.geom.set_shader_input('light_radius', float(self.__radius))
            self.geom.set_shader_input('light_pos', Vec4(self.__pos, 1.0))
            self.geom.set_shader_input('light_fov', deg2Rad(fov))
            self.geom.set_shader_input('spot', self.p3d_light)
        self.__fov = fov

    def set_radius(self, radius):
        """
        Sets the radius (range) of the light
        """
        self.geom.set_shader_input("light_radius", float(radius))
        self.geom.set_scale(radius)
        self.__radius = radius
        try:
            self.p3d_light.node().get_lens().set_near_far(0.1, radius)
        except:
            pass

    def setHpr(self, hpr):
        """
        Sets the HPR of a light
        """
        self.geom.set_hpr(hpr)
        self.p3d_light.set_hpr(hpr)
        self.__hpr = hrp

    def set_pos(self, *args):
        """
        Sets light position,
        you can pass in a NodePath as the first argument to make the pos relative to that node
        """
        if len(args) < 1:
            return
        elif len(args) == 1:  # one arg, must be a vector
            pos = Vec3(args[0])
        elif len(args) == 2:  # two args, must be a node and  vector
            pos = render.get_relative_point(args[0], Vec3(args[1]))
        elif len(args) == 3:  # vector
            pos = Vec3(args[0], args[1], args[2])
        elif len(args) == 4:  # node and vector?
            pos = render.get_relative_point(
                args[0], Vec3(args[0], args[1], args[2]))
        else:  # something ???
            pos = Vec3(args[0], args[1], args[2])
        self.geom.set_pos(pos)
        self.p3d_light.set_pos(pos)
        self.__pos = pos

    def lookAt(self, node_or_pos):
        """
        Sets the hpr of the light so that it looks at the given node or pos
        """
        self.look_at(node_or_pos)

    def look_at(self, node_or_pos):
        """
        Sets the hpr of the light so that it looks at the given node or pos
        """
        self.geom.look_at(node_or_pos)
        self.p3d_light.look_at(node_or_pos)
        self.__hpr = self.p3d_light.get_hpr(render)

    def set_shadow_bias(self, bias):
        self.__shadow_bias=bias
        if bias is not None:
            self.geom.set_shader_input("bias", bias)

    def remove(self):
        self.geom.removeNode()
        try:
            buff = self.p3d_light.node().get_shadow_buffer(base.win.get_gsg())
            buff.clear_render_textures()
            base.win.get_gsg().get_engine().remove_window(buff)
            self.p3d_light.node().set_shadow_caster(False)
        except:
            pass
        self.p3d_light.remove_node()

    def __del__(self):
        try:
            self.remove()
        except:
            pass

    @property
    def fov(self):
        return self.__fov

    @fov.setter
    def fov(self, f):
        self.set_fov(f)

    @property
    def hpr(self):
        return self.geom.get_hpr(render)

    @hpr.setter
    def hpr(self, p):
        self.setHpr(p)

    @property
    def pos(self):
        return self.geom.get_pos(render)

    @pos.setter
    def pos(self, p):
        self.set_pos(p)

    @property
    def color(self):
        return self.__color

    @color.setter
    def color(self, c):
        self.set_color(c)

    @property
    def radius(self):
        return self.__radius

    @radius.setter
    def radius(self, r):
        self.set_radius(float(r))