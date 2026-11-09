.. meta::
   :description: Flash, reset and test Zephyr on boards in a labgrid lab.

.. _index:

zephyr-labgrid
==============

``zephyr-labgrid`` lets you flash, reset and test Zephyr on boards in a
`labgrid <https://labgrid.readthedocs.io/>`_ lab with the usual ``west``
and Twister commands. Zephyr and labgrid stay unchanged.

This is an experimental release (0.1), tested with Zephyr 4.5 and labgrid
master on an STM32F746G-DISCO, an ESP32-DevKitC and an Alif Ensemble E8
DevKit.

Where to start
--------------

:ref:`quickstart`
   A complete lab on one machine, to try the module.
:ref:`flash-and-test`
   Flash, reset and run Twister on lab boards.
:ref:`prepare-a-lab`
   Make labgrid places ready for Zephyr users.
:ref:`design`
   How it works inside, for contributors.

How the pieces fit together
---------------------------

.. image:: images/pieces-light.svg
   :class: only-light
   :alt: The runner and labgrid-pty on the developer host reach the flash tool
         and ser2net on the exporter host. Both hosts keep a session with the
         labgrid coordinator, which holds places, owners and tags.

.. image:: images/pieces-dark.svg
   :class: only-dark
   :alt: The runner and labgrid-pty on the developer host reach the flash tool
         and ser2net on the exporter host. Both hosts keep a session with the
         labgrid coordinator, which holds places, owners and tags.

The module adds the ``labgrid`` west runner and the ``labgrid-pty`` console
bridge on the developer side. The flash tool runs on the exporter next to
the board. The complete :external+labgrid:doc:`labgrid documentation <index>` and the
:external+zephyr:doc:`Twister documentation <develop/twister/index>` help
when you need options beyond the workflows here.

.. toctree::
   :hidden:

   quickstart
   flash-and-test
   prepare-a-lab
   design
