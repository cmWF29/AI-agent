/* 前端通信中枢：领域事件 + 实例通道 + 挂载注册。
 * 模块只声明“我渲染什么、订阅什么”，核心路由只发布“哪个实例该挂载了”。
 */
(function (global) {
  var subs = {};
  var modules = {};
  var mounted = {};

  function on(topic, handler) {
    (subs[topic] = subs[topic] || []).push(handler);
    return function () {
      var list = subs[topic] || [];
      var i = list.indexOf(handler);
      if (i >= 0) list.splice(i, 1);
    };
  }

  function emit(topic, payload) {
    var list = (subs[topic] || []).slice();
    for (var i = 0; i < list.length; i++) {
      try { list[i](payload || {}); } catch (e) { if (global.console) console.error(e); }
    }
  }

  function define(name, mod) {
    modules[name] = mod || {};
    return modules[name];
  }

  function mount(domain, instanceId, containerId) {
    var payload = { instanceId: instanceId, domain: domain, mountContainerId: containerId };
    if (domain === 'project') payload.projectId = instanceId;
    mounted[domain + ':' + instanceId] = containerId;
    emit(domain + ':mounted', payload);
  }

  function unmount(domain, instanceId) {
    var key = domain + ':' + instanceId;
    var containerId = mounted[key];
    emit(domain + ':unmounted', { instanceId: instanceId, mountContainerId: containerId });
    delete mounted[key];
  }

  function instanceTopic(domain, instanceId, action) {
    return domain + ':' + instanceId + ':' + action;
  }

  function emitInstance(domain, instanceId, action, payload) {
    emit(instanceTopic(domain, instanceId, action), payload || {});
  }

  global.HiveUI = {
    on: on, emit: emit, define: define, mount: mount, unmount: unmount,
    instanceTopic: instanceTopic, emitInstance: emitInstance,
    modules: modules,
  };
})(window);
